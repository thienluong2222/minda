"""Minimal model-backed end-to-end pipeline for the initial local prototype."""

from __future__ import annotations

import csv
import json
import math
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
import torch
import torchaudio
from scipy.signal import resample_poly
from speechbrain.inference.separation import SepformerSeparation
from speechbrain.utils.fetching import FetchConfig

from meeting_pipeline.adapters.audio_io import decode_mono, probe_audio, sha256_file
from meeting_pipeline.adapters.phowhisper_asr import BaseAsrAdapter, PhoWhisperAsrAdapter
from meeting_pipeline.adapters.pyannote_segmentation import PyannoteSegmentationAdapter
from meeting_pipeline.application.speakers import SpeakerProfileInput, SpeakerRegistry
from meeting_pipeline.config import PipelineConfig
from meeting_pipeline.domain.errors import AlignmentError
from meeting_pipeline.domain.schemas import TimelineSegment
from meeting_pipeline.domain.speaker_classifier import (
    BaseSpeakerClassifier,
    ECAPASpeakerClassifier,
    MFCCKNNSpeakerClassifier,
)
from meeting_pipeline.domain.transcription import (
    AsrChunk,
    ChunkTranscript,
    SpeechRegion,
)
from meeting_pipeline.pipeline.stages.activity_detection import ActivityDetector
from meeting_pipeline.pipeline.stages.chunking import ChunkPlanner
from meeting_pipeline.pipeline.stages.fuse import CandidateEvidence, identity_weights
from meeting_pipeline.pipeline.stages.sentence_segmentation import SentenceSegmenter
from meeting_pipeline.pipeline.stages.synchronize import estimate_offset, union_coverage
from meeting_pipeline.pipeline.stages.transcript_stitching import TranscriptStitcher


@dataclass(slots=True)
class PreparedSource:
    """Decoded source and its position on the common meeting clock."""

    source_id: str
    original_path: Path
    analysis_path: Path
    samples: np.ndarray
    sha256: str
    offset_sec: float = 0.0
    alignment_status: str = "reference"
    peak_ratio: float | None = None


@dataclass(frozen=True, slots=True)
class ActivityRegion:
    """Contiguous speech interval with one or two active local speakers."""

    start_sec: float
    end_sec: float
    speaker_count: int


class PrototypePipeline:
    """Run the mandatory audio stages without the deferred application/web surface."""

    def __init__(
        self,
        config: PipelineConfig,
        activity_detector: ActivityDetector | None = None,
        chunk_planner: ChunkPlanner | None = None,
        asr_adapter: BaseAsrAdapter | None = None,
        transcript_stitcher: TranscriptStitcher | None = None,
        sentence_segmenter: SentenceSegmenter | None = None,
    ) -> None:
        self.config = config
        self.sample_rate = config.audio.analysis_sample_rate
        self.cache = config.paths.model_cache_dir
        self._separator: SepformerSeparation | None = None
        self._speaker_encoder = SpeakerRegistry(config)
        self._profiles: list[SpeakerProfileInput] = []
        self._speaker_classifier: BaseSpeakerClassifier | None = None
        self._max_anonymous = 1

        self.activity_detector = activity_detector
        self.chunk_planner = chunk_planner or ChunkPlanner(config.asr, sample_rate=self.sample_rate)
        self.asr_adapter = asr_adapter
        self.transcript_stitcher = transcript_stitcher or TranscriptStitcher()
        self.sentence_segmenter = sentence_segmenter or SentenceSegmenter(
            sentence_pause_seconds=float(config.asr.sentence_pause_seconds),
            max_sentence_seconds=float(config.asr.max_sentence_seconds),
        )

    def _get_activity_detector(self) -> ActivityDetector:
        if self.activity_detector is None:
            checkpoint = (
                self._snapshot(
                    "pyannote/segmentation-3.0",
                    str(self.config.models["segmentation_revision"]),
                )
                / "pytorch_model.bin"
            )
            pyannote_adapter = PyannoteSegmentationAdapter(
                checkpoint, step_seconds=float(self.config.segmentation.step_seconds)
            )
            self.activity_detector = ActivityDetector(
                config=self.config.segmentation,
                sample_rate=self.sample_rate,
                pyannote_adapter=pyannote_adapter,
            )
        return self.activity_detector

    def _get_asr_adapter(self) -> BaseAsrAdapter:
        if self.asr_adapter is None:
            self.asr_adapter = PhoWhisperAsrAdapter(self.config.asr, self.cache)
        return self.asr_adapter

    def run(
        self,
        meeting_name: str,
        source_paths: list[Path],
        speaker_profiles: list[SpeakerProfileInput] | None = None,
    ) -> Path:
        """Process one meeting and return its immutable run directory."""
        if not 1 <= len(source_paths) <= self.config.audio.max_sources:
            raise ValueError("Source count is outside configured prototype limits")
        self._profiles = list(speaker_profiles or [])
        self._max_anonymous = max(2, len(source_paths))
        identity_method = str(self.config.identity.get("method", "prototype_cosine"))
        identity_threshold = float(str(self.config.identity.get("identity_threshold", 0.25)))
        identity_margin = float(str(self.config.identity.get("identity_margin", 0.05)))
        anonymous_cluster_threshold = float(
            str(self.config.identity.get("anonymous_cluster_threshold", 0.10))
        )

        if identity_method == "mfcc_knn":
            knn_config = self.config.identity.get("knn", {})
            mfcc_config = self.config.identity.get("mfcc", {})
            n_neighbors = (
                int(knn_config.get("n_neighbors", 5)) if isinstance(knn_config, dict) else 5
            )
            metric = (
                str(knn_config.get("metric", "cosine"))
                if isinstance(knn_config, dict)
                else "cosine"
            )
            n_mfcc = int(mfcc_config.get("n_mfcc", 20)) if isinstance(mfcc_config, dict) else 20
            window_sec = (
                float(mfcc_config.get("window_sec", 1.5)) if isinstance(mfcc_config, dict) else 1.5
            )
            step_sec = (
                float(mfcc_config.get("step_sec", 0.5)) if isinstance(mfcc_config, dict) else 0.5
            )

            self._speaker_classifier = MFCCKNNSpeakerClassifier(
                profiles=self._profiles,
                n_neighbors=n_neighbors,
                metric=metric,
                identity_threshold=identity_threshold,
                identity_margin=identity_margin,
                anonymous_cluster_threshold=anonymous_cluster_threshold,
                max_anonymous=self._max_anonymous,
                sample_rate=self.sample_rate,
                n_mfcc=n_mfcc,
                window_sec=window_sec,
                step_sec=step_sec,
            )
        else:
            self._speaker_classifier = ECAPASpeakerClassifier(
                encoder=self._speaker_encoder,
                profiles=self._profiles,
                identity_threshold=identity_threshold,
                identity_margin=identity_margin,
                anonymous_cluster_threshold=anonymous_cluster_threshold,
                max_anonymous=self._max_anonymous,
                sample_rate=self.sample_rate,
            )

        run_id = str(uuid.uuid4())
        meeting_id = _safe_id(meeting_name)
        run_dir = self.config.paths.data_dir / "meetings" / meeting_id / "runs" / run_id
        for directory in (
            "decoded",
            "aligned",
            "clips/original",
            "clips/processed",
            "clips/asr-input",
            "clips/evidence",
            "exports",
        ):
            (run_dir / directory).mkdir(parents=True, exist_ok=True)
        sources = self._prepare_sources(source_paths, run_dir)
        reference = max(sources, key=lambda source: source.samples.size)
        self._align_sources(sources, reference)
        origin_shift, coverage = union_coverage(
            [
                (_mapping(source.offset_sec), source.samples.size / self.sample_rate)
                for source in sources
            ]
        )
        for source in sources:
            source.offset_sec += origin_shift
        meeting_duration = max(end for _, end in coverage)
        aligned = self._write_aligned(sources, meeting_duration, run_dir)

        # Stage A: Multi-source activity detection
        activity_detector = self._get_activity_detector()
        regions = activity_detector.detect(sources, meeting_duration)
        valid_sources = [s.source_id for s in sources if s.alignment_status != "alignment_failed"]
        activity_payload = {
            "schema_version": "1.0",
            "meeting_duration": meeting_duration,
            "valid_sources": valid_sources,
            "config": {
                "merge_gap_ms": self.config.segmentation.merge_gap_ms,
                "minimum_speech_ms": self.config.segmentation.minimum_speech_ms,
                "speech_pad_ms": self.config.segmentation.speech_pad_ms,
                "vad_threshold": self.config.segmentation.vad_threshold,
            },
            "regions": [region.model_dump() for region in regions],
        }
        _write_json(run_dir / "activity_regions.json", activity_payload)

        # Stage B - F: Process regions into timeline
        timeline = self._process_regions(regions, sources, aligned, meeting_duration, run_dir)
        coverage_payload = self._coverage_payload(sources)
        _write_json(run_dir / "coverage.json", coverage_payload)
        _write_json(run_dir / "timeline.json", {"schema_version": "1.0", "segments": timeline})
        manifest: dict[str, object] = {
            "schema_version": "1.0",
            "run_id": run_id,
            "meeting_name": meeting_name,
            "status": "succeeded",
            "speaker_mode": "enrollment_or_stable_anonymous",
            "speaker_profiles": [profile.speaker_id for profile in self._profiles],
            "models": self._model_revisions(),
            "inputs": {source.source_id: source.sha256 for source in sources},
            "artifacts": [
                "coverage.json",
                "activity_regions.json",
                "asr_chunks.json",
                "chunk_transcripts.json",
                "stitched_transcript.json",
                "timeline.json",
                "aligned/",
                "clips/",
                "exports/",
            ],
        }
        _write_json(run_dir / "manifest.json", manifest)
        self._write_exports(run_dir, timeline)
        return run_dir

    def _write_exports(self, run_dir: Path, timeline: list[dict[str, object]]) -> None:
        exports = run_dir / "exports"
        _write_json(exports / "result.json", {"schema_version": "1.0", "segments": timeline})
        with (exports / "result.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "start_sec",
                    "end_sec",
                    "speaker_status",
                    "speaker_id",
                    "speaker_label",
                    "text",
                    "source_id",
                ]
            )
            for segment in timeline:
                writer.writerow(
                    [
                        segment["start_sec"],
                        segment["end_sec"],
                        segment["speaker_status"],
                        segment.get("speaker_id") or "",
                        segment.get("speaker_label") or "",
                        segment["text"],
                        segment.get("selected_source_id") or "",
                    ]
                )
        with (exports / "result.txt").open("w", encoding="utf-8") as handle:
            for segment in timeline:
                handle.write(
                    f"[{float(str(segment['start_sec'])):.2f}-"
                    f"{float(str(segment['end_sec'])):.2f}] "
                    f"{segment.get('speaker_label') or 'Unknown'}: {segment['text']}\n"
                )
        with zipfile.ZipFile(exports / "result.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(run_dir.rglob("*")):
                if path.is_file() and path != exports / "result.zip":
                    archive.write(path, path.relative_to(run_dir))

    def _prepare_sources(self, paths: list[Path], run_dir: Path) -> list[PreparedSource]:
        sources: list[PreparedSource] = []
        seen: set[str] = set()
        for index, path in enumerate(paths):
            metadata = probe_audio(path)
            if metadata.duration_sec > self.config.audio.max_duration_seconds:
                raise ValueError(f"Source exceeds duration limit: {path.name}")
            checksum = sha256_file(path)
            if checksum in seen:
                raise ValueError(f"Duplicate source content: {path.name}")
            seen.add(checksum)
            source_id = f"source-{index + 1}"
            decoded = run_dir / "decoded" / f"{source_id}.wav"
            decode_mono(path, decoded, self.sample_rate)
            samples, rate = sf.read(decoded, dtype="float32")
            if rate != self.sample_rate or samples.ndim != 1:
                raise ValueError("Decoded analysis audio violates mono/rate contract")
            sources.append(PreparedSource(source_id, path, decoded, samples, checksum))
        return sources

    def _align_sources(self, sources: list[PreparedSource], reference: PreparedSource) -> None:
        for source in sources:
            if source is reference:
                continue
            try:
                estimate = estimate_offset(
                    reference.samples,
                    source.samples,
                    self.sample_rate,
                    int(self.config.sync.envelope_rate_hz),
                    float(self.config.sync.max_offset_seconds),
                )
                source.offset_sec = estimate.mapping.offset_sec
                source.peak_ratio = estimate.peak_ratio
                source.alignment_status = estimate.status
            except AlignmentError:
                source.alignment_status = "alignment_failed"

    def _write_aligned(
        self,
        sources: list[PreparedSource],
        duration_sec: float,
        run_dir: Path,
    ) -> dict[str, np.ndarray]:
        total = math.ceil(duration_sec * self.sample_rate)
        result: dict[str, np.ndarray] = {}
        for source in sources:
            output = np.zeros(total, dtype=np.float32)
            start = max(0, round(source.offset_sec * self.sample_rate))
            end = min(total, start + source.samples.size)
            output[start:end] = source.samples[: end - start]
            sf.write(run_dir / "aligned" / f"{source.source_id}.wav", output, self.sample_rate)
            result[source.source_id] = output
        return result

    def _detect_activity(
        self, sources: list[PreparedSource], meeting_duration: float
    ) -> list[SpeechRegion]:
        return self._get_activity_detector().detect(sources, meeting_duration)

    def _process_regions(
        self,
        regions: list[SpeechRegion],
        sources: list[PreparedSource],
        aligned: dict[str, np.ndarray],
        meeting_duration: float,
        run_dir: Path,
    ) -> list[dict[str, object]]:
        timeline: list[dict[str, object]] = []
        if not regions:
            _write_json(run_dir / "asr_chunks.json", {"schema_version": "1.0", "chunks": []})
            _write_json(
                run_dir / "chunk_transcripts.json",
                {"schema_version": "1.0", "transcripts": []},
            )
            _write_json(
                run_dir / "stitched_transcript.json",
                {
                    "schema_version": "1.0",
                    "words": [],
                    "full_text": "",
                    "warnings": [],
                    "discarded_overlap_count": 0,
                },
            )
            return []

        raw_weights = self.config.identity["quality_weights"]
        if not isinstance(raw_weights, list) or len(raw_weights) != 3:
            raise ValueError("identity.quality_weights must contain three values")
        coefficients = (
            float(str(raw_weights[0])),
            float(str(raw_weights[1])),
            float(str(raw_weights[2])),
        )
        temperature = float(str(self.config.identity["temperature"]))

        preferred_source_map: dict[str, str] = {}
        region_quality: dict[
            str, tuple[list[CandidateEvidence], dict[str, float], PreparedSource]
        ] = {}
        region_original_file: dict[str, str] = {}

        for region in regions:
            candidates = self._quality_candidates(region, sources, aligned)
            alpha = identity_weights(candidates, coefficients, temperature)
            selected_id = max(alpha, key=lambda s_id: alpha[s_id])
            selected = next(s for s in sources if s.source_id == selected_id)
            preferred_source_map[region.region_id] = selected_id
            region_quality[region.region_id] = (candidates, alpha, selected)

            source_start = max(
                0, round((region.start_sec - selected.offset_sec) * self.sample_rate)
            )
            source_end = min(
                selected.samples.size,
                round((region.end_sec - selected.offset_sec) * self.sample_rate),
            )
            original = selected.samples[source_start:source_end]
            orig_id = f"segment-{region.region_id[:8]}-{selected_id}-original.wav"
            sf.write(run_dir / "clips/original" / orig_id, original, self.sample_rate)
            region_original_file[region.region_id] = orig_id

        # Separate single-speaker and overlap regions
        single_speaker_regions = [r for r in regions if r.speaker_count != 2]
        overlap_regions = [r for r in regions if r.speaker_count == 2]

        # 1. Overlap handling (SepFormer)
        for region in overlap_regions:
            candidates, alpha, selected = region_quality[region.region_id]
            selected_id = selected.source_id
            start = round(region.start_sec * self.sample_rate)
            end = round(region.end_sec * self.sample_rate)
            context = float(str(self.config.separation["context_seconds"]))
            context_start = max(0, start - round(context * self.sample_rate))
            context_end = min(aligned[selected_id].size, end + round(context * self.sample_rate))
            expanded_tracks = self._separate(aligned[selected_id][context_start:context_end])
            crop_start = start - context_start
            tracks = [track[crop_start : crop_start + end - start] for track in expanded_tracks]
            overlap_group = str(uuid.uuid4())
            used_speakers: set[str] = set()

            for track_index, waveform in enumerate(tracks):
                seg_id = str(uuid.uuid4())
                clip_id = f"segment-{region.region_id[:8]}-track-{track_index + 1}.wav"
                processed, gain = _peak_limit(waveform)
                clip_path = run_dir / "clips/processed" / clip_id
                sf.write(clip_path, processed, self.sample_rate, subtype="PCM_16")

                ev_clip_path = run_dir / "clips/evidence" / f"{seg_id}.wav"
                sf.write(ev_clip_path, processed, self.sample_rate, subtype="PCM_16")
                ev_artifact_id = f"clips/evidence/{seg_id}.wav"

                asr_waveform, _ = sf.read(clip_path, dtype="float32")
                speaker = self._assign_speaker(asr_waveform, used_speakers)
                used_speakers.add(str(speaker["speaker_id"]))
                asr_res = self._get_asr_adapter().transcribe(asr_waveform, self.sample_rate)
                text = asr_res.text

                source_start = max(
                    0, round((region.start_sec - selected.offset_sec) * self.sample_rate)
                )
                source_end = min(
                    selected.samples.size,
                    round((region.end_sec - selected.offset_sec) * self.sample_rate),
                )

                timeline.append(
                    {
                        "segment_id": seg_id,
                        "track_id": str(speaker["speaker_id"]),
                        "start_sec": region.start_sec,
                        "end_sec": region.end_sec,
                        "speaker_id": speaker.get("profile_id"),
                        "speaker_label": speaker.get("speaker_label"),
                        "speaker_status": speaker.get("speaker_status", "unknown"),
                        "speaker_match_score": speaker.get("speaker_match_score"),
                        "speaker_top_candidates": speaker.get("speaker_top_candidates", []),
                        "identity_decision_reason": speaker.get("identity_decision_reason", ""),
                        "overlap_group_id": overlap_group,
                        "text": text,
                        "asr_status": "transcribed" if text else "empty",
                        "needs_review": True,
                        "warnings": speaker.get("warnings", []),
                        "selected_source_id": selected_id,
                        "selected_spans": [
                            {
                                "source_id": selected_id,
                                "candidate_id": f"{selected_id}-candidate-{track_index + 1}",
                                "interval": {
                                    "start_sec": region.start_sec,
                                    "end_sec": region.end_sec,
                                },
                            }
                        ],
                        "source_evidence": [
                            {
                                "source_id": candidate.source_id,
                                "available": candidate.eligible,
                                "eligible": candidate.eligible,
                                "identity_weight": alpha[candidate.source_id],
                                "selection_weight": alpha[candidate.source_id],
                                "raw_quality_features": {
                                    "speech_presence": candidate.speech_presence,
                                    "speech_noise_contrast": candidate.speech_noise_contrast,
                                    "clipping_avoidance": candidate.clipping_avoidance,
                                },
                                "candidate_scores": {},
                            }
                            for candidate in candidates
                        ],
                        "original_clip_artifact_ids": [
                            f"clips/original/{region_original_file[region.region_id]}"
                        ],
                        "processed_clip_artifact_id": f"clips/processed/{clip_id}",
                        "asr_input_artifact_id": f"clips/processed/{clip_id}",
                        "alternative_clip_artifact_ids": [],
                        "evidence_clip_artifact_id": ev_artifact_id,
                        "speech_region_id": region.region_id,
                        "asr_chunk_ids": [],
                        "provenance": {
                            "original_spans": [
                                {
                                    "source_id": selected_id,
                                    "start_sample": source_start,
                                    "end_sample": max(source_start + 1, source_end),
                                    "start_sec": round(source_start / self.sample_rate, 4),
                                    "end_sec": round(
                                        max(source_start + 1, source_end) / self.sample_rate, 4
                                    ),
                                    "mapping_id": f"mapping-{selected_id}",
                                }
                            ],
                            "speech_interval": {
                                "start_sec": region.start_sec,
                                "end_sec": region.end_sec,
                            },
                            "clip_interval": {
                                "start_sec": region.start_sec,
                                "end_sec": region.end_sec,
                            },
                            "transform_chain": [
                                "decode_mono_16k",
                                "align_offset",
                                "sepformer_8k_to_16k",
                                f"peak_limit_gain={gain:.8f}",
                                "pcm16_roundtrip_asr_input",
                                "phowhisper_small",
                            ],
                            "separation_model_revision": str(
                                self.config.separation["model_revision"]
                            ),
                            "speaker_profile_version": None,
                            "asr_model_revision": str(self.config.asr["model_revision"]),
                        },
                    }
                )

        # 2. Single-speaker chunking & transcription
        chunks: list[AsrChunk] = []
        chunk_transcripts: list[ChunkTranscript] = []

        if single_speaker_regions:
            chunks = self.chunk_planner.plan(
                regions=single_speaker_regions,
                meeting_duration=meeting_duration,
                source_audio_map=aligned,
                preferred_source_map=preferred_source_map,
            )

            for chunk in chunks:
                c_start = round(chunk.clip_interval.start_sec * self.sample_rate)
                c_end = round(chunk.clip_interval.end_sec * self.sample_rate)
                chunk_audio = aligned[chunk.source_id][c_start:c_end]
                processed_chunk, _ = _peak_limit(chunk_audio)
                chunk_clip_path = run_dir / chunk.clip_artifact_id
                chunk_clip_path.parent.mkdir(parents=True, exist_ok=True)
                sf.write(chunk_clip_path, processed_chunk, self.sample_rate, subtype="PCM_16")

                waveform, _ = sf.read(chunk_clip_path, dtype="float32")
                ct = self._get_asr_adapter().transcribe_chunk(chunk, waveform, self.sample_rate)
                chunk_transcripts.append(ct)

        _write_json(
            run_dir / "asr_chunks.json",
            {
                "schema_version": "1.0",
                "chunks": [chunk.model_dump() for chunk in chunks],
            },
        )
        _write_json(
            run_dir / "chunk_transcripts.json",
            {
                "schema_version": "1.0",
                "transcripts": [ct.model_dump() for ct in chunk_transcripts],
            },
        )

        # 3. Stitch transcripts
        stitched = self.transcript_stitcher.stitch(chunk_transcripts, chunks)
        _write_json(
            run_dir / "stitched_transcript.json",
            {
                "schema_version": "1.0",
                "words": [w.model_dump() for w in stitched.words],
                "full_text": stitched.full_text,
                "warnings": stitched.warnings,
                "discarded_overlap_count": stitched.discarded_overlap_count,
            },
        )

        # 4. Sentence segmentation
        sentences = self.sentence_segmenter.segment(
            words=stitched.words,
            speech_regions=single_speaker_regions,
        )

        # 5. Build timeline rows for sentences
        for sentence in sentences:
            parent_region: SpeechRegion | None = None
            if sentence.speech_region_id:
                parent_region = next(
                    (r for r in single_speaker_regions if r.region_id == sentence.speech_region_id),
                    None,
                )
            if parent_region is None:
                mid = (sentence.start_sec + sentence.end_sec) / 2.0
                for r in single_speaker_regions:
                    if r.start_sec - 1e-4 <= mid <= r.end_sec + 1e-4:
                        parent_region = r
                        break
            if parent_region is None and single_speaker_regions:
                parent_region = single_speaker_regions[0]

            if parent_region is None:
                continue

            candidates, alpha, selected = region_quality[parent_region.region_id]
            selected_id = selected.source_id

            matching_chunk_ids = [
                c.chunk_id
                for c in chunks
                if max(c.core_interval.start_sec, sentence.start_sec)
                < min(c.core_interval.end_sec, sentence.end_sec) + 1e-4
            ]
            if not matching_chunk_ids and chunks:
                matching_chunk_ids = [chunks[0].chunk_id]

            # Evidence clip with padding clamped to meeting bounds & source coverage
            pad_sec = float(self.config.asr.evidence_pad_seconds)
            raw_start = sentence.start_sec - pad_sec
            raw_end = sentence.end_sec + pad_sec

            cov_start = selected.offset_sec
            cov_end = selected.offset_sec + selected.samples.size / self.sample_rate
            ev_start = max(0.0, cov_start, raw_start)
            ev_end = min(meeting_duration, cov_end, raw_end)

            evidence_artifact_id: str | None = None
            evidence_waveform = np.zeros(0, dtype=np.float32)
            gain = 1.0

            if ev_end > ev_start + 1e-4:
                s_idx = round(ev_start * self.sample_rate)
                e_idx = round(ev_end * self.sample_rate)
                raw_ev = aligned[selected_id][s_idx:e_idx]
                processed_ev, gain = _peak_limit(raw_ev)
                ev_clip_path = run_dir / "clips/evidence" / f"{sentence.sentence_id}.wav"
                sf.write(ev_clip_path, processed_ev, self.sample_rate, subtype="PCM_16")
                evidence_artifact_id = f"clips/evidence/{sentence.sentence_id}.wav"
                evidence_waveform, _ = sf.read(ev_clip_path, dtype="float32")

            # Speaker identification on evidence audio
            if evidence_waveform.size > 0 and np.max(np.abs(evidence_waveform), initial=0.0) > 1e-5:
                speaker = self._assign_speaker(evidence_waveform, set())
            else:
                speaker = {
                    "speaker_id": "unknown",
                    "profile_id": None,
                    "speaker_label": "Unknown",
                    "speaker_status": "unknown",
                    "speaker_match_score": None,
                    "speaker_top_candidates": [],
                    "identity_decision_reason": "insufficient_audio",
                    "warnings": ["insufficient_audio_for_speaker_id"],
                }

            src_sample_start = max(0, round((ev_start - selected.offset_sec) * self.sample_rate))
            src_sample_end = min(
                selected.samples.size, round((ev_end - selected.offset_sec) * self.sample_rate)
            )
            first_chunk = next((c for c in chunks if c.chunk_id in matching_chunk_ids), None)
            asr_input_art = first_chunk.clip_artifact_id if first_chunk else None

            raw_spk_warnings = speaker.get("warnings")
            speaker_warnings: list[str] = (
                [str(w) for w in raw_spk_warnings] if isinstance(raw_spk_warnings, list) else []
            )
            all_warnings = list(dict.fromkeys(sentence.warnings + speaker_warnings))
            needs_review = (
                sentence.needs_review or (evidence_artifact_id is None) or bool(sentence.warnings)
            )

            timeline.append(
                {
                    "segment_id": sentence.sentence_id,
                    "track_id": str(speaker["speaker_id"]),
                    "start_sec": sentence.start_sec,
                    "end_sec": sentence.end_sec,
                    "speaker_id": speaker.get("profile_id"),
                    "speaker_label": speaker.get("speaker_label"),
                    "speaker_status": speaker.get("speaker_status", "unknown"),
                    "speaker_match_score": speaker.get("speaker_match_score"),
                    "speaker_top_candidates": speaker.get("speaker_top_candidates", []),
                    "identity_decision_reason": speaker.get("identity_decision_reason", ""),
                    "overlap_group_id": None,
                    "text": sentence.text,
                    "asr_status": "transcribed" if sentence.text else "empty",
                    "needs_review": needs_review,
                    "warnings": all_warnings,
                    "selected_source_id": selected_id,
                    "selected_spans": [
                        {
                            "source_id": selected_id,
                            "candidate_id": f"{selected_id}-candidate",
                            "interval": {
                                "start_sec": sentence.start_sec,
                                "end_sec": sentence.end_sec,
                            },
                        }
                    ],
                    "source_evidence": [
                        {
                            "source_id": candidate.source_id,
                            "available": candidate.eligible,
                            "eligible": candidate.eligible,
                            "identity_weight": alpha[candidate.source_id],
                            "selection_weight": alpha[candidate.source_id],
                            "raw_quality_features": {
                                "speech_presence": candidate.speech_presence,
                                "speech_noise_contrast": candidate.speech_noise_contrast,
                                "clipping_avoidance": candidate.clipping_avoidance,
                            },
                            "candidate_scores": {},
                        }
                        for candidate in candidates
                    ],
                    "original_clip_artifact_ids": [
                        f"clips/original/{region_original_file[parent_region.region_id]}"
                    ],
                    "processed_clip_artifact_id": evidence_artifact_id,
                    "asr_input_artifact_id": asr_input_art,
                    "alternative_clip_artifact_ids": [],
                    "evidence_clip_artifact_id": evidence_artifact_id,
                    "speech_region_id": parent_region.region_id,
                    "asr_chunk_ids": matching_chunk_ids,
                    "provenance": {
                        "original_spans": [
                            {
                                "source_id": selected_id,
                                "start_sample": src_sample_start,
                                "end_sample": max(src_sample_start + 1, src_sample_end),
                                "start_sec": round(src_sample_start / self.sample_rate, 4),
                                "end_sec": round(
                                    max(src_sample_start + 1, src_sample_end) / self.sample_rate, 4
                                ),
                                "mapping_id": f"mapping-{selected_id}",
                            }
                        ],
                        "speech_interval": {
                            "start_sec": sentence.start_sec,
                            "end_sec": sentence.end_sec,
                        },
                        "clip_interval": {
                            "start_sec": round(ev_start, 4),
                            "end_sec": round(max(ev_start + 0.001, ev_end), 4),
                        },
                        "transform_chain": [
                            "decode_mono_16k",
                            "align_offset",
                            "selected_mixture",
                            f"peak_limit_gain={gain:.8f}",
                            "pcm16_evidence_clip",
                            "phowhisper_small",
                        ],
                        "separation_model_revision": None,
                        "speaker_profile_version": None,
                        "asr_model_revision": str(self.config.asr["model_revision"]),
                    },
                }
            )

        timeline.sort(key=lambda seg: (float(str(seg["start_sec"])), float(str(seg["end_sec"]))))

        for seg in timeline:
            TimelineSegment.model_validate(seg)

        return timeline

    def _assign_speaker(self, waveform: np.ndarray, excluded: set[str]) -> dict[str, object]:
        """Delegate speaker assignment to the configured classifier."""
        if self._speaker_classifier is None:
            raise RuntimeError("Speaker classifier not initialized")
        return self._speaker_classifier.assign_speaker(waveform, excluded)

    def _quality_candidates(
        self,
        region: Any,
        sources: list[PreparedSource],
        aligned: dict[str, np.ndarray],
    ) -> list[CandidateEvidence]:
        start = round(region.start_sec * self.sample_rate)
        end = round(region.end_sec * self.sample_rate)
        candidates: list[CandidateEvidence] = []
        for source in sources:
            clip = aligned[source.source_id][start:end]
            available = (
                source.alignment_status != "alignment_failed"
                and region.start_sec >= source.offset_sec
                and region.end_sec <= source.offset_sec + source.samples.size / self.sample_rate
            )
            rms = float(np.sqrt(np.mean(np.square(clip), dtype=np.float64))) if clip.size else 0.0
            speech_presence = float(1.0 - np.exp(-rms / 0.04))
            frame_size = max(1, round(0.02 * self.sample_rate))
            usable = clip.size - clip.size % frame_size
            if usable:
                frames = clip[:usable].reshape(-1, frame_size)
                frame_rms = np.sqrt(np.mean(np.square(frames), axis=1))
                low, high = np.percentile(frame_rms, [20, 80])
                contrast = float(np.clip((high - low) / max(high, 1e-8), 0, 1))
            else:
                contrast = 0.0
            clipping = 1.0 - min(1.0, float(np.mean(np.abs(clip) >= 0.999)) * 100)
            candidates.append(
                CandidateEvidence(
                    source.source_id,
                    available and rms > 1e-5,
                    speech_presence,
                    contrast,
                    clipping,
                    {},
                )
            )
        if not any(candidate.eligible for candidate in candidates):
            raise ValueError("No eligible source for detected speech region")
        return candidates

    def _separate(self, mixture: np.ndarray) -> list[np.ndarray]:
        if self._separator is None:
            revision = str(self.config.separation["model_revision"])
            self._separator = SepformerSeparation.from_hparams(
                source="speechbrain/sepformer-whamr",
                savedir=self.config.paths.data_dir / "runtime" / "sepformer",
                run_opts={"device": "cpu"},
                fetch_config=FetchConfig(
                    allow_network=False,
                    revision=revision,
                    huggingface_cache_dir=self.cache,
                ),
            )
        tensor = torch.from_numpy(mixture).unsqueeze(0)
        at_8k = torchaudio.functional.resample(tensor, self.sample_rate, 8000)
        separated = self._separator.separate_batch(at_8k).squeeze(0).detach().cpu().numpy()
        return [
            resample_poly(separated[:, index], self.sample_rate, 8000).astype(np.float32)
            for index in range(2)
        ]

    def _transcribe(self, waveform: np.ndarray) -> str:
        return self._get_asr_adapter().transcribe(waveform, self.sample_rate).text

    def _transcribe_window(self, waveform: np.ndarray) -> str:
        return self._transcribe(waveform)

    def _coverage_payload(self, sources: list[PreparedSource]) -> dict[str, object]:
        return {
            "sample_rate": self.sample_rate,
            "sources": [
                {
                    "source_id": source.source_id,
                    "original_name": source.original_path.name,
                    "start_sec": source.offset_sec,
                    "end_sec": source.offset_sec + source.samples.size / self.sample_rate,
                    "offset_sec": source.offset_sec,
                    "scale": 1.0,
                    "alignment_status": source.alignment_status,
                    "peak_ratio": source.peak_ratio,
                }
                for source in sources
            ],
        }

    def _snapshot(self, model_id: str, revision: str) -> Path:
        path = self.cache / ("models--" + model_id.replace("/", "--")) / "snapshots" / revision
        if not path.is_dir():
            raise FileNotFoundError(f"Prepared model snapshot is missing: {model_id}@{revision}")
        return path

    def _model_revisions(self) -> dict[str, str]:
        return {
            "segmentation": str(self.config.models["segmentation_revision"]),
            "separation": str(self.config.separation["model_revision"]),
            "asr": str(self.config.asr["model_revision"]),
        }


def _mapping(offset_sec: float) -> Any:
    from meeting_pipeline.domain.time_mapping import AffineTimeMapping

    return AffineTimeMapping(1.0, offset_sec)


def _peak_limit(waveform: np.ndarray, target: float = 0.95) -> tuple[np.ndarray, float]:
    """Apply attenuation only, preventing PCM serialization clipping without boosting noise."""
    samples = np.asarray(waveform, dtype=np.float32)
    peak = float(np.max(np.abs(samples), initial=0.0))
    gain = min(1.0, target / peak) if peak > 0 else 1.0
    return np.asarray(samples * gain, dtype=np.float32), gain


def _states_to_regions(
    states: np.ndarray, bin_sec: float, minimum_sec: float
) -> list[ActivityRegion]:
    regions: list[ActivityRegion] = []
    start = 0
    state = int(states[0]) if states.size else 0
    for index in range(1, states.size + 1):
        next_state = int(states[index]) if index < states.size else -1
        if next_state == state:
            continue
        if state > 0 and (index - start) * bin_sec >= minimum_sec:
            regions.append(ActivityRegion(start * bin_sec, index * bin_sec, state))
        start, state = index, next_state
    return regions


def _safe_id(value: str) -> str:
    normalized = "".join(character.lower() if character.isalnum() else "-" for character in value)
    return normalized.strip("-") or "meeting"


def _write_json(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
