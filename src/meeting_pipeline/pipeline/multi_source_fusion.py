"""Production-facing multi-source transcript fusion pipeline for the web demo.

The experimental F0-F6 modules operate on prepared synthetic meetings.  This
adapter applies the same contracts to arbitrary user uploads while preserving
the artifact schema consumed by the FastAPI demo.
"""

from __future__ import annotations

import csv
import json
import re
import uuid
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from meeting_pipeline.adapters.audio_io import decode_mono, probe_audio, sha256_file
from meeting_pipeline.adapters.phowhisper_asr import BaseAsrAdapter, PhoWhisperAsrAdapter
from meeting_pipeline.application.speakers import SpeakerProfileInput
from meeting_pipeline.asr.segment_asr import transcribe_segment_sources
from meeting_pipeline.audio.synchronization import (
    extract_shared_meeting_segments,
    synchronize_multi_source_audio,
)
from meeting_pipeline.config import PipelineConfig
from meeting_pipeline.domain.contracts import MeetingSegment, SourceHypothesis, VadConfig
from meeting_pipeline.domain.speaker_classifier import MFCCKNNSpeakerClassifier
from meeting_pipeline.fusion.baselines import (
    fuse_f0_fixed,
    fuse_f1_best_segment,
    fuse_f3_rover,
    fuse_f4_asr_weighted,
    fuse_f5_rule_weighted,
    fuse_f6_learned,
)
from meeting_pipeline.fusion.confusion_network import ConfusionBin, build_confusion_network
from meeting_pipeline.fusion.features import compute_transcript_quality_score
from meeting_pipeline.fusion.model import LearnedFusionModel
from meeting_pipeline.fusion.provenance import build_final_timeline_item
from meeting_pipeline.pipeline.overlap_separation import TwoSpeakerSeparator
from meeting_pipeline.pipeline.speaker_turns import SpeakerTurn, SpeakerTurnDetector
from meeting_pipeline.speaker.encoder import ECAPAEncoder

FloatArray = np.ndarray[Any, np.dtype[np.float32]]
SegmentExtractor = Callable[[dict[str, FloatArray], VadConfig, str, int], list[MeetingSegment]]

SUPPORTED_FUSION_METHODS = {
    "F0_FIXED",
    "F1_BEST_SEGMENT",
    "F3_ROVER",
    "F4_ASR_WEIGHTED",
    "F5_RULE_WEIGHTED",
    "F6_LEARNED",
}


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _safe_id(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-").lower()
    return normalized[:80] or "meeting"


def _normalized_weights(scores: dict[str, float], temperature: float = 1.0) -> dict[str, float]:
    if not scores:
        return {}
    powered = {key: max(1e-4, value) ** temperature for key, value in scores.items()}
    total = sum(powered.values())
    return {key: value / total for key, value in powered.items()}


class _MultiSourceSpeakerAssigner:
    """Assign enrolled speakers from a quality-weighted ECAPA embedding."""

    def __init__(self, config: PipelineConfig, profiles: list[SpeakerProfileInput]) -> None:
        self.config = config
        self.profiles = profiles
        self.sample_rate = config.audio.analysis_sample_rate
        self.encoder = ECAPAEncoder(
            model_id=str(config.identity["model_id"]),
            revision=str(config.identity["model_revision"]),
            cache_dir=config.paths.model_cache_dir,
        )
        self.anonymous_centroids: list[FloatArray] = []
        self.anonymous_counts: list[int] = []

    def assign(
        self,
        waveforms: dict[str, FloatArray],
        quality_scores: dict[str, float],
        excluded_speaker_ids: set[str] | None = None,
    ) -> dict[str, object]:
        excluded = excluded_speaker_ids or set()
        embeddings: dict[str, FloatArray] = {}
        for source_id, waveform in waveforms.items():
            signal = waveform
            if signal.size < self.sample_rate:
                signal = np.pad(signal, (0, self.sample_rate - signal.size)).astype(np.float32)
            if np.max(np.abs(signal), initial=0.0) < 1e-6:
                continue
            embeddings[source_id] = self.encoder.encode(signal)

        if not embeddings:
            return self._insufficient_audio()

        weights = _normalized_weights(
            {source_id: quality_scores.get(source_id, 0.5) for source_id in embeddings},
            float(str(self.config.identity.get("temperature", 1.5))),
        )
        fused = np.sum(
            np.stack([embeddings[source_id] * weights[source_id] for source_id in embeddings]),
            axis=0,
        ).astype(np.float32)
        fused /= max(float(np.linalg.norm(fused)), 1e-12)

        ranked = sorted(
            (
                (profile, float(np.dot(fused, profile.embedding)))
                for profile in self.profiles
                if profile.speaker_id not in excluded
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        threshold = float(str(self.config.identity.get("identity_threshold", 0.25)))
        margin = float(str(self.config.identity.get("identity_margin", 0.05)))
        candidates = [
            {"speaker_id": profile.speaker_id, "cosine_score": score}
            for profile, score in ranked[:3]
        ]

        if ranked:
            best_profile, best_score = ranked[0]
            runner_up = ranked[1][1] if len(ranked) > 1 else -1.0
            actual_margin = best_score - runner_up
            if best_score >= threshold and actual_margin >= margin:
                return {
                    "speaker_id": best_profile.speaker_id,
                    "profile_id": best_profile.speaker_id,
                    "speaker_label": best_profile.display_name,
                    "speaker_status": "identified",
                    "speaker_match_score": best_score,
                    "speaker_top_candidates": candidates,
                    "identity_decision_reason": (
                        f"multi_source_ecapa: score={best_score:.3f}, margin={actual_margin:.3f}"
                    ),
                    "warnings": [],
                    "source_weights": weights,
                }

        return self._anonymous(fused, ranked, candidates, weights, excluded)

    def _anonymous(
        self,
        embedding: FloatArray,
        ranked: list[tuple[SpeakerProfileInput, float]],
        candidates: list[dict[str, object]],
        source_weights: dict[str, float],
        excluded_speaker_ids: set[str],
    ) -> dict[str, object]:
        threshold = float(str(self.config.identity.get("anonymous_cluster_threshold", 0.1)))
        max_anonymous = max(2, int(self.config.audio.max_profiles))
        similarities = [float(np.dot(embedding, centroid)) for centroid in self.anonymous_centroids]
        available = [
            i for i in range(len(similarities)) if f"anonymous-{i + 1}" not in excluded_speaker_ids
        ]
        best_index = max(available, key=lambda i: similarities[i]) if available else -1
        reuse = best_index >= 0 and (
            similarities[best_index] >= threshold or len(self.anonymous_centroids) >= max_anonymous
        )
        if reuse:
            count = self.anonymous_counts[best_index]
            centroid = np.asarray(
                (self.anonymous_centroids[best_index] * count + embedding) / (count + 1),
                dtype=np.float32,
            )
            centroid /= max(float(np.linalg.norm(centroid)), 1e-12)
            self.anonymous_centroids[best_index] = centroid
            self.anonymous_counts[best_index] += 1
            cluster_score: float | None = similarities[best_index]
            cluster_reason = f"cluster_reuse={cluster_score:.3f}"
        else:
            self.anonymous_centroids.append(embedding)
            self.anonymous_counts.append(1)
            best_index = len(self.anonymous_centroids) - 1
            cluster_score = None
            cluster_reason = "new_cluster"

        enrollment_reason = "no_enrollment_profiles"
        if ranked:
            enrollment_reason = f"enrollment_rejected={ranked[0][1]:.3f}"
        return {
            "speaker_id": f"anonymous-{best_index + 1}",
            "profile_id": None,
            "speaker_label": f"Speaker {best_index + 1}",
            "speaker_status": "unknown",
            "speaker_match_score": cluster_score,
            "speaker_top_candidates": candidates,
            "identity_decision_reason": f"{enrollment_reason} -> {cluster_reason}",
            "warnings": ["speaker_not_enrolled_or_below_threshold"],
            "source_weights": source_weights,
        }

    @staticmethod
    def _insufficient_audio() -> dict[str, object]:
        return {
            "speaker_id": "unknown",
            "profile_id": None,
            "speaker_label": "Unknown",
            "speaker_status": "unknown",
            "speaker_match_score": None,
            "speaker_top_candidates": [],
            "identity_decision_reason": "insufficient_audio",
            "warnings": ["insufficient_audio_for_speaker_id"],
            "source_weights": {},
        }


class MultiSourceFusionPipeline:
    """Run synchronization, shared VAD, per-source ASR, fusion, and speaker ID."""

    def __init__(
        self,
        config: PipelineConfig,
        asr_adapter: BaseAsrAdapter | None = None,
        segment_extractor: SegmentExtractor | None = None,
        turn_detector: SpeakerTurnDetector | None = None,
        separator: TwoSpeakerSeparator | None = None,
    ) -> None:
        self.config = config
        self.sample_rate = config.audio.analysis_sample_rate
        self.asr_adapter = asr_adapter
        self.segment_extractor = segment_extractor or extract_shared_meeting_segments
        self.turn_detector = turn_detector
        self.separator = separator

    def run(
        self,
        meeting_name: str,
        source_paths: list[Path],
        speaker_profiles: list[SpeakerProfileInput] | None = None,
        fusion_method: str = "F5_RULE_WEIGHTED",
    ) -> Path:
        if not 1 <= len(source_paths) <= self.config.audio.max_sources:
            raise ValueError("Source count is outside configured limits")
        requested_method = fusion_method.strip().upper()
        if requested_method not in SUPPORTED_FUSION_METHODS:
            raise ValueError(f"Unsupported fusion method: {fusion_method}")

        run_id = str(uuid.uuid4())
        meeting_id = _safe_id(meeting_name)
        run_dir = self.config.paths.data_dir / "meetings" / meeting_id / "runs" / run_id
        for directory in ("decoded", "aligned", "clips/evidence", "exports"):
            (run_dir / directory).mkdir(parents=True, exist_ok=True)

        decoded, source_rows = self._decode_sources(source_paths, run_dir)
        aligned, sync_metadata, reference_source = synchronize_multi_source_audio(
            decoded, sample_rate=self.sample_rate
        )
        for source_id, signal in aligned.items():
            sf.write(run_dir / "aligned" / f"{source_id}.wav", signal, self.sample_rate)

        vad_config = VadConfig(
            threshold=self.config.segmentation.vad_threshold,
            min_speech_sec=self.config.segmentation.minimum_speech_ms / 1000.0,
            min_silence_sec=self.config.segmentation.minimum_silence_ms / 1000.0,
            merge_gap_sec=self.config.segmentation.merge_gap_ms / 1000.0,
            padding_sec=self.config.segmentation.speech_pad_ms / 1000.0,
            max_segment_sec=min(15.0, self.config.asr.max_chunk_seconds),
        )
        segments = self.segment_extractor(aligned, vad_config, meeting_id, self.sample_rate)
        _write_json(
            run_dir / "activity_regions.json",
            {
                "schema_version": "2.0",
                "backend": "multi_source_transcript_fusion",
                "reference_source_id": reference_source,
                "segments": [segment.model_dump() for segment in segments],
            },
        )

        checkpoint = (
            self.config.paths.model_cache_dir
            / "models--pyannote--segmentation-3.0"
            / "snapshots"
            / str(self.config.models["segmentation_revision"])
            / "pytorch_model.bin"
        )
        if self.turn_detector is None:
            self.turn_detector = SpeakerTurnDetector(
                checkpoint, self.config.segmentation.step_seconds
            )
        aligned_paths = {
            source_id: run_dir / "aligned" / f"{source_id}.wav" for source_id in aligned
        }
        duration_sec = max(len(signal) for signal in aligned.values()) / self.sample_rate
        turns = self.turn_detector.detect(aligned_paths, segments, reference_source, duration_sec)
        _write_json(
            run_dir / "speaker_turns.json",
            {
                "schema_version": "1.0",
                "model": f"pyannote/segmentation-3.0@{self.config.models['segmentation_revision']}",
                "turns": [turn.as_dict() for turn in turns],
            },
        )

        profiles = list(speaker_profiles or [])
        ecapa_assigner = _MultiSourceSpeakerAssigner(self.config, profiles)
        mfcc_assigner = self._build_mfcc_assigner(profiles)
        learned_model = self._load_learned_model()
        actual_method = requested_method
        run_warnings: list[str] = []
        if requested_method == "F6_LEARNED" and not learned_model.is_fitted:
            actual_method = "F5_RULE_WEIGHTED"
            run_warnings.append("F6 model chưa được huấn luyện; đã dùng F5_RULE_WEIGHTED")

        timeline: list[dict[str, object]] = []
        all_hypotheses: list[dict[str, object]] = []
        all_decisions: list[dict[str, object]] = []
        skipped_overlap_groups: set[str] = set()
        track_speakers: dict[str, dict[str, object]] = {}
        previous_turn: SpeakerTurn | None = None
        for turn in turns:
            if turn.speaker_count == 2:
                # Keep one reviewable timeline row per overlap interval. Separation,
                # ASR and speaker identification are intentionally deferred here.
                group_id = turn.overlap_group_id or turn.turn_id
                if group_id in skipped_overlap_groups:
                    continue
                skipped_overlap_groups.add(group_id)
                timeline.append(self._skipped_overlap_row(turn, aligned, run_dir))
                all_hypotheses.append(
                    {
                        "segment_id": turn.turn_id,
                        "turn_id": turn.turn_id,
                        "speech_region_id": turn.speech_region_id,
                        "overlap_group_id": group_id,
                        "sources": {},
                    }
                )
                all_decisions.append(
                    {
                        "segment_id": turn.turn_id,
                        "turn_id": turn.turn_id,
                        "overlap_group_id": group_id,
                        "fusion_method": actual_method,
                        "fused_text": "",
                        "word_decisions": [],
                    }
                )
                previous_turn = None
                continue

            segment = MeetingSegment(
                meeting_id=meeting_id,
                segment_id=turn.turn_id,
                start_sec=turn.start_sec,
                end_sec=turn.end_sec,
                overlap=False,
            )
            turn_warnings = list(turn.warnings)
            segment_waves = self._slice_segment(aligned, segment)
            hypotheses = transcribe_segment_sources(
                meeting_id,
                segment,
                segment_waves,
                self._get_asr_adapter(),
                sample_rate=self.sample_rate,
            )
            agreement = self._apply_cross_source_agreement(hypotheses)
            bins = build_confusion_network(hypotheses)
            fused_text, word_decisions = self._fuse(
                actual_method, hypotheses, bins, learned_model, reference_source
            )
            final_item = build_final_timeline_item(
                meeting_id=meeting_id,
                segment=segment,
                fused_text=fused_text,
                word_decisions=word_decisions,
                speaker_id="pending",
                speaker_confidence=0.0,
                source_hypotheses=hypotheses,
                aligned_audio_signals=aligned,
                output_clips_dir=run_dir / "clips" / "evidence",
                sample_rate=self.sample_rate,
            )
            audio_scores = {
                source_id: hypothesis.audio_quality_score
                for source_id, hypothesis in hypotheses.items()
            }
            excluded: set[str] = set()
            if (
                previous_turn is not None
                and previous_turn.speech_region_id == turn.speech_region_id
                and previous_turn.track_id != turn.track_id
                and previous_turn.end_sec >= turn.start_sec - 0.1
                and previous_turn.track_id in track_speakers
            ):
                excluded.add(str(track_speakers[previous_turn.track_id]["speaker_id"]))
            if str(self.config.identity.get("method", "prototype_cosine")) == "mfcc_knn":
                primary_wave = segment_waves.get(final_item.primary_source_id)
                if primary_wave is None:
                    primary_wave = next(iter(segment_waves.values()))
                speaker = mfcc_assigner.assign_speaker(primary_wave, excluded)
                speaker["source_weights"] = _normalized_weights(audio_scores, 1.0)
            else:
                speaker = ecapa_assigner.assign(segment_waves, audio_scores, excluded)
            if turn.track_id in track_speakers and not turn.track_id.startswith("unresolved"):
                previous_identity = track_speakers[turn.track_id]
                if previous_identity.get("speaker_id") != speaker.get("speaker_id"):
                    turn_warnings.append("speaker_identity_inconsistent_with_track")
            track_speakers[turn.track_id] = speaker
            timeline_row = self._timeline_row(
                final_item.model_dump(),
                hypotheses,
                agreement,
                speaker,
                run_dir,
                actual_method,
            )
            timeline_row["speech_region_id"] = turn.speech_region_id
            timeline_row["turn_id"] = turn.turn_id
            timeline_row["track_id"] = turn.track_id
            timeline_row["overlap_group_id"] = turn.overlap_group_id
            timeline_row["speaker_count"] = turn.speaker_count
            provenance = timeline_row["provenance"]
            if isinstance(provenance, dict):
                provenance["turn_id"] = turn.turn_id
                provenance["speech_region_id"] = turn.speech_region_id
            if turn_warnings:
                timeline_row["needs_review"] = True
                row_warnings = timeline_row["warnings"]
                timeline_row["warnings"] = list(
                    dict.fromkeys(
                        [
                            *(row_warnings if isinstance(row_warnings, list) else []),
                            *turn_warnings,
                        ]
                    )
                )
            timeline.append(timeline_row)
            all_hypotheses.append(
                {
                    "segment_id": segment.segment_id,
                    "turn_id": turn.turn_id,
                    "speech_region_id": turn.speech_region_id,
                    "overlap_group_id": turn.overlap_group_id,
                    "sources": {
                        source_id: hypothesis.model_dump()
                        for source_id, hypothesis in hypotheses.items()
                    },
                }
            )
            all_decisions.append(
                {
                    "segment_id": segment.segment_id,
                    "turn_id": turn.turn_id,
                    "speech_region_id": turn.speech_region_id,
                    "overlap_group_id": turn.overlap_group_id,
                    "fusion_method": actual_method,
                    "fused_text": fused_text,
                    "word_decisions": word_decisions,
                }
            )
            previous_turn = turn

        self._write_artifacts(
            run_dir,
            meeting_name,
            run_id,
            timeline,
            source_rows,
            sync_metadata,
            reference_source,
            all_hypotheses,
            all_decisions,
            requested_method,
            actual_method,
            run_warnings,
            profiles,
        )
        return run_dir

    def _separate_overlap(
        self,
        aligned: dict[str, FloatArray],
        turns: list[SpeakerTurn],
        track_anchors: dict[str, FloatArray],
        run_dir: Path,
    ) -> tuple[dict[str, dict[str, FloatArray]], list[str]]:
        """Separate each source, then match arbitrary stream order across phones."""
        tracks = sorted({turn.track_id for turn in turns})
        if len(tracks) != 2:
            return {}, ["overlap_did_not_have_exactly_two_tracks"]
        start_sec, end_sec = turns[0].start_sec, turns[0].end_sec
        if self.separator is None:
            self.separator = TwoSpeakerSeparator(
                model_id=str(self.config.separation["model_id"]),
                revision=str(self.config.separation["model_revision"]),
                model_cache_dir=self.config.paths.model_cache_dir,
                runtime_dir=run_dir / "runtime" / "sepformer",
                sample_rate=self.sample_rate,
                separator_sample_rate=self.config.audio.separator_sample_rate,
            )
        warnings: list[str] = []
        separated: dict[str, list[FloatArray]] = {}
        for source_id, signal in aligned.items():
            try:
                tracks_for_source = self.separator.separate(
                    signal,
                    start_sec,
                    end_sec,
                    float(str(self.config.separation.get("context_seconds", 1.0))),
                )
                if len(tracks_for_source) != 2 or any(
                    self._rms(wave) < 1e-5 for wave in tracks_for_source
                ):
                    raise ValueError("separator returned a silent/missing stream")
                separated[source_id] = tracks_for_source
            except Exception as exc:
                warnings.append(f"separation_failed:{source_id}:{type(exc).__name__}")
        if not separated:
            return {}, warnings or ["separation_failed_all_sources"]

        def embed(wave: FloatArray) -> FloatArray:
            if len(wave) < self.sample_rate:
                wave = np.pad(wave, (0, self.sample_rate - len(wave))).astype(np.float32)
            return self._overlap_encoder.encode(wave)

        # A clean neighboring turn can anchor a stream to an established local track.
        self._overlap_encoder = getattr(self, "_overlap_encoder", None) or ECAPAEncoder(
            model_id=str(self.config.identity["model_id"]),
            revision=str(self.config.identity["model_revision"]),
            cache_dir=self.config.paths.model_cache_dir,
        )
        base_id = next(iter(separated))
        base = separated[base_id]
        base_vectors = [embed(wave) for wave in base]
        anchors = [track_anchors.get(track) for track in tracks]
        if all(anchor is not None for anchor in anchors):
            anchor0, anchor1 = anchors
            assert anchor0 is not None and anchor1 is not None
            direct = float(np.dot(base_vectors[0], anchor0) + np.dot(base_vectors[1], anchor1))
            swapped = float(np.dot(base_vectors[1], anchor0) + np.dot(base_vectors[0], anchor1))
            base_order = (0, 1) if direct >= swapped else (1, 0)
            if abs(direct - swapped) < 0.10:
                warnings.append("overlap_track_anchor_ambiguous")
        elif any(anchor is not None for anchor in anchors):
            anchor_index = 0 if anchors[0] is not None else 1
            anchor = anchors[anchor_index]
            assert anchor is not None
            best_stream = int(np.argmax([float(np.dot(vector, anchor)) for vector in base_vectors]))
            base_order = (
                (best_stream, 1 - best_stream)
                if anchor_index == 0
                else (1 - best_stream, best_stream)
            )
            warnings.append("overlap_only_one_clean_anchor")
        else:
            base_order = (0, 1)
            warnings.append("overlap_tracks_unanchored")

        result: dict[str, dict[str, FloatArray]] = {
            tracks[0]: {base_id: base[base_order[0]]},
            tracks[1]: {base_id: base[base_order[1]]},
        }
        target_vectors = [base_vectors[base_order[0]], base_vectors[base_order[1]]]
        for source_id, source_tracks in separated.items():
            if source_id == base_id:
                continue
            vectors = [embed(wave) for wave in source_tracks]
            direct = float(
                np.dot(vectors[0], target_vectors[0]) + np.dot(vectors[1], target_vectors[1])
            )
            swapped = float(
                np.dot(vectors[1], target_vectors[0]) + np.dot(vectors[0], target_vectors[1])
            )
            if max(direct, swapped) / 2 < 0.30 or abs(direct - swapped) < 0.10:
                warnings.append(f"separated_stream_alignment_ambiguous:{source_id}")
                continue
            order = (0, 1) if direct >= swapped else (1, 0)
            for index, track_id in enumerate(tracks):
                result[track_id][source_id] = source_tracks[order[index]]
        return result, warnings

    @staticmethod
    def _rms(signal: FloatArray) -> float:
        return float(np.sqrt(np.mean(signal.astype(np.float64) ** 2))) if signal.size else 0.0

    def _write_original_overlap_clips(
        self, aligned: dict[str, FloatArray], turn: SpeakerTurn, run_dir: Path
    ) -> None:
        directory = run_dir / "clips" / "original" / turn.turn_id
        directory.mkdir(parents=True, exist_ok=True)
        start = round(turn.start_sec * self.sample_rate)
        end = round(turn.end_sec * self.sample_rate)
        for source_id, signal in aligned.items():
            sf.write(directory / f"{source_id}.wav", signal[start:end], self.sample_rate)

    @staticmethod
    def _original_overlap_clip_ids(
        aligned: dict[str, FloatArray], turn: SpeakerTurn, run_dir: Path
    ) -> list[str]:
        return [
            str(
                (run_dir / "clips" / "original" / turn.turn_id / f"{source_id}.wav").relative_to(
                    run_dir
                )
            )
            for source_id in aligned
        ]

    def _replace_evidence_with_processed(
        self, item: dict[str, Any], waveforms: dict[str, FloatArray]
    ) -> None:
        paths = item.get("evidence_clips", {})
        if not isinstance(paths, dict):
            return
        for source_id, signal in waveforms.items():
            if source_id in paths:
                sf.write(str(paths[source_id]), signal, self.sample_rate, subtype="PCM_16")

    def _skipped_overlap_row(
        self,
        turn: SpeakerTurn,
        aligned: dict[str, FloatArray],
        run_dir: Path,
    ) -> dict[str, object]:
        """Keep original audio and timing without guessing either speaker's words."""
        self._write_original_overlap_clips(aligned, turn, run_dir)
        original = self._original_overlap_clip_ids(aligned, turn, run_dir)
        source_id = next(iter(aligned))
        return {
            "segment_id": turn.turn_id,
            "turn_id": turn.turn_id,
            "speech_region_id": turn.speech_region_id,
            "track_id": None,
            "speaker_count": turn.speaker_count,
            "start_sec": turn.start_sec,
            "end_sec": turn.end_sec,
            "speaker_id": None,
            "speaker_label": "Chưa xác định",
            "speaker_status": "unknown",
            "speaker_match_score": None,
            "speaker_top_candidates": [],
            "identity_decision_reason": "overlap_skipped",
            "overlap_group_id": turn.overlap_group_id,
            "text": "",
            "transcript_confidence": None,
            "fusion_method": None,
            "asr_status": "not_run",
            "needs_review": True,
            "warnings": list(dict.fromkeys([*turn.warnings, "overlap_skipped"])),
            "selected_source_id": source_id,
            "selected_spans": [
                {
                    "source_id": source_id,
                    "interval": {"start_sec": turn.start_sec, "end_sec": turn.end_sec},
                }
            ],
            "source_evidence": [],
            "original_clip_artifact_ids": original,
            "processed_clip_artifact_id": None,
            "asr_input_artifact_id": None,
            "alternative_clip_artifact_ids": original[1:],
            "evidence_clip_artifact_id": original[0],
            "asr_chunk_ids": [turn.turn_id],
            "provenance": {
                "turn_id": turn.turn_id,
                "speech_region_id": turn.speech_region_id,
                "overlap_status": "skipped",
            },
        }

    def _get_asr_adapter(self) -> BaseAsrAdapter:
        if self.asr_adapter is None:
            self.asr_adapter = PhoWhisperAsrAdapter(
                self.config.asr, self.config.paths.model_cache_dir
            )
        return self.asr_adapter

    def _load_learned_model(self) -> LearnedFusionModel:
        candidates = [
            Path("artifacts/full/learned_fusion_model.joblib"),
            Path("artifacts/smoke/learned_fusion_model.joblib"),
        ]
        for path in candidates:
            if path.is_file():
                return LearnedFusionModel.load(path)
        return LearnedFusionModel()

    def _decode_sources(
        self, source_paths: list[Path], run_dir: Path
    ) -> tuple[dict[str, FloatArray], list[dict[str, object]]]:
        decoded: dict[str, FloatArray] = {}
        rows: list[dict[str, object]] = []
        checksums: set[str] = set()
        for index, source_path in enumerate(source_paths, start=1):
            metadata = probe_audio(source_path)
            if metadata.duration_sec > self.config.audio.max_duration_seconds:
                raise ValueError(f"Source exceeds duration limit: {source_path.name}")
            checksum = sha256_file(source_path)
            if checksum in checksums:
                raise ValueError(f"Duplicate source content: {source_path.name}")
            checksums.add(checksum)
            source_id = f"source-{index}"
            decoded_path = run_dir / "decoded" / f"{source_id}.wav"
            decode_mono(source_path, decoded_path, self.sample_rate)
            waveform, sample_rate = sf.read(decoded_path, dtype="float32")
            if sample_rate != self.sample_rate or waveform.ndim != 1:
                raise ValueError("Decoded audio violates mono/rate contract")
            decoded[source_id] = np.asarray(waveform, dtype=np.float32)
            rows.append(
                {
                    "source_id": source_id,
                    "original_name": source_path.name,
                    "sha256": checksum,
                    "duration_sec": metadata.duration_sec,
                }
            )
        return decoded, rows

    def _slice_segment(
        self, aligned: dict[str, FloatArray], segment: MeetingSegment
    ) -> dict[str, FloatArray]:
        start = max(0, round(segment.start_sec * self.sample_rate))
        end = max(start + 1, round(segment.end_sec * self.sample_rate))
        return {
            source_id: np.asarray(signal[start:end], dtype=np.float32)
            for source_id, signal in aligned.items()
        }

    @staticmethod
    def _apply_cross_source_agreement(
        hypotheses: dict[str, SourceHypothesis],
    ) -> dict[str, float | None]:
        if not hypotheses:
            return {}
        bins = build_confusion_network(hypotheses)
        agreement: dict[str, float | None] = {}
        valid_count = sum(
            hyp.asr_status == "transcribed" and bool(hyp.text.strip())
            for hyp in hypotheses.values()
        )
        for source_id, hypothesis in hypotheses.items():
            if hypothesis.asr_status != "transcribed" or not hypothesis.text.strip():
                hypothesis.transcript_quality_score = 0.0
                hypothesis.asr_features["word_agreement"] = None
                agreement[source_id] = None
                continue
            matched = 0
            observed = 0
            for confusion_bin in bins:
                token = confusion_bin.candidates.get(source_id, "<eps>")
                if token == "<eps>":
                    continue
                observed += 1
                if sum(value == token for value in confusion_bin.candidates.values()) >= 2:
                    matched += 1
            ratio = matched / observed if observed and valid_count > 1 else None
            measured_confidence = hypothesis.asr_features.get("mean_confidence")
            # The neutral values below are only ranking heuristics, not model probabilities.
            ranking_confidence = (
                float(measured_confidence) if measured_confidence is not None else 0.5
            )
            hypothesis.transcript_quality_score = round(
                compute_transcript_quality_score(
                    hypothesis.audio_quality_score,
                    ranking_confidence,
                    ratio if ratio is not None else 0.5,
                ),
                4,
            )
            hypothesis.asr_features["word_agreement"] = (
                round(ratio, 4) if ratio is not None else None
            )
            agreement[source_id] = ratio
        return agreement

    @staticmethod
    def _fuse(
        method: str,
        hypotheses: dict[str, SourceHypothesis],
        bins: list[ConfusionBin],
        learned_model: LearnedFusionModel,
        reference_source: str,
    ) -> tuple[str, list[dict[str, Any]]]:
        hypotheses = {
            source_id: hyp
            for source_id, hyp in hypotheses.items()
            if hyp.asr_status == "transcribed" and hyp.text.strip()
        }
        if method == "F0_FIXED":
            return fuse_f0_fixed(hypotheses, reference_source)
        if method == "F1_BEST_SEGMENT":
            return fuse_f1_best_segment(hypotheses)
        if method == "F3_ROVER":
            return fuse_f3_rover(bins)
        if method == "F4_ASR_WEIGHTED":
            return fuse_f4_asr_weighted(bins)
        if method == "F6_LEARNED":
            return fuse_f6_learned(bins, learned_model)
        return fuse_f5_rule_weighted(bins)

    def _build_mfcc_assigner(self, profiles: list[SpeakerProfileInput]) -> MFCCKNNSpeakerClassifier:
        mfcc_config = self.config.identity.get("mfcc", {})
        knn_config = self.config.identity.get("knn", {})
        mfcc = mfcc_config if isinstance(mfcc_config, dict) else {}
        knn = knn_config if isinstance(knn_config, dict) else {}
        return MFCCKNNSpeakerClassifier(
            profiles=profiles,
            n_neighbors=int(knn.get("n_neighbors", 5)),
            metric=str(knn.get("metric", "cosine")),
            identity_threshold=float(str(self.config.identity.get("identity_threshold", 0.25))),
            identity_margin=float(str(self.config.identity.get("identity_margin", 0.05))),
            anonymous_cluster_threshold=float(
                str(self.config.identity.get("anonymous_cluster_threshold", 0.1))
            ),
            max_anonymous=max(2, self.config.audio.max_profiles),
            sample_rate=self.sample_rate,
            n_mfcc=int(mfcc.get("n_mfcc", 20)),
            window_sec=float(mfcc.get("window_sec", 1.5)),
            step_sec=float(mfcc.get("step_sec", 0.5)),
        )

    @staticmethod
    def _timeline_row(
        item: dict[str, Any],
        hypotheses: dict[str, SourceHypothesis],
        agreement: dict[str, float | None],
        speaker: dict[str, object],
        run_dir: Path,
        fusion_method: str,
    ) -> dict[str, object]:
        primary_source = str(item["primary_source_id"])
        quality_scores = {
            source_id: hypothesis.transcript_quality_score
            for source_id, hypothesis in hypotheses.items()
            if hypothesis.asr_status == "transcribed" and hypothesis.text.strip()
        }
        fusion_weights = _normalized_weights(quality_scores, 1.0)
        raw_identity_weights = speaker.get("source_weights", {})
        identity_weights = (
            {str(key): float(value) for key, value in raw_identity_weights.items()}
            if isinstance(raw_identity_weights, dict)
            else {}
        )
        raw_evidence_clips = item.get("evidence_clips", {})
        evidence_clips = (
            {
                str(source_id): str(Path(str(path)).resolve().relative_to(run_dir.resolve()))
                for source_id, path in raw_evidence_clips.items()
            }
            if isinstance(raw_evidence_clips, dict)
            else {}
        )
        primary_clip = evidence_clips.get(primary_source)
        raw_warnings = speaker.get("warnings", [])
        warnings = [str(value) for value in raw_warnings] if isinstance(raw_warnings, list) else []
        if not item.get("text"):
            warnings.append("empty_fused_transcript")
        rejected = [hyp for hyp in hypotheses.values() if hyp.asr_status == "unreliable"]
        for hypothesis in rejected:
            warnings.extend(hypothesis.asr_warnings)
        confidence = item.get("transcript_confidence")
        if confidence is not None and float(confidence) < 0.5:
            warnings.append("low_transcript_confidence")

        source_evidence = []
        for source_id, hypothesis in hypotheses.items():
            source_evidence.append(
                {
                    "source_id": source_id,
                    "available": True,
                    "eligible": hypothesis.asr_status == "transcribed"
                    and bool(hypothesis.text.strip()),
                    "asr_status": hypothesis.asr_status,
                    "asr_warnings": hypothesis.asr_warnings,
                    "identity_weight": identity_weights.get(source_id, 0.0),
                    "selection_weight": fusion_weights.get(source_id, 0.0),
                    "raw_quality_features": hypothesis.audio_features,
                    "candidate_scores": {
                        "transcript": hypothesis.text,
                        "audio_quality_score": hypothesis.audio_quality_score,
                        "asr_confidence": hypothesis.asr_features.get("mean_confidence"),
                        "word_agreement": agreement.get(source_id),
                        "transcript_quality_score": hypothesis.transcript_quality_score,
                    },
                    "evidence_clip_artifact_id": evidence_clips.get(source_id),
                }
            )

        word_provenance = item.get("word_provenance", [])
        return {
            "segment_id": item["segment_id"],
            "track_id": str(speaker.get("speaker_id", "unknown")),
            "start_sec": item["start_sec"],
            "end_sec": item["end_sec"],
            "speaker_id": speaker.get("profile_id"),
            "speaker_label": speaker.get("speaker_label", "Unknown"),
            "speaker_status": speaker.get("speaker_status", "unknown"),
            "speaker_match_score": speaker.get("speaker_match_score"),
            "speaker_top_candidates": speaker.get("speaker_top_candidates", []),
            "identity_decision_reason": speaker.get("identity_decision_reason", ""),
            "overlap_group_id": None,
            "text": item.get("text", ""),
            "transcript_confidence": item.get("transcript_confidence"),
            "fusion_method": fusion_method,
            "asr_status": (
                "transcribed"
                if item.get("text")
                else "unreliable"
                if rejected
                else "failed"
                if any(h.asr_status == "failed" for h in hypotheses.values())
                else "empty"
            ),
            "needs_review": bool(warnings),
            "warnings": list(dict.fromkeys(warnings)),
            "selected_source_id": primary_source,
            "selected_spans": [
                {
                    "source_id": primary_source,
                    "interval": {"start_sec": item["start_sec"], "end_sec": item["end_sec"]},
                }
            ],
            "source_evidence": source_evidence,
            "original_clip_artifact_ids": [
                value for value in evidence_clips.values() if value is not None
            ],
            "processed_clip_artifact_id": primary_clip,
            "asr_input_artifact_id": primary_clip,
            "alternative_clip_artifact_ids": [
                value for source_id, value in evidence_clips.items() if source_id != primary_source
            ],
            "evidence_clip_artifact_id": primary_clip,
            "speech_region_id": item["segment_id"],
            "asr_chunk_ids": [item["segment_id"]],
            "provenance": {
                "fusion_method": fusion_method,
                "primary_source_id": primary_source,
                "word_provenance": word_provenance,
            },
        }

    def _write_artifacts(
        self,
        run_dir: Path,
        meeting_name: str,
        run_id: str,
        timeline: list[dict[str, object]],
        source_rows: list[dict[str, object]],
        sync_metadata: dict[str, dict[str, float]],
        reference_source: str,
        hypotheses: list[dict[str, object]],
        decisions: list[dict[str, object]],
        requested_method: str,
        actual_method: str,
        warnings: list[str],
        profiles: list[SpeakerProfileInput],
    ) -> None:
        coverage_sources = []
        for row in source_rows:
            source_id = str(row["source_id"])
            coverage_sources.append({**row, "synchronization": sync_metadata[source_id]})
        _write_json(
            run_dir / "coverage.json",
            {
                "schema_version": "2.0",
                "reference_source_id": reference_source,
                "sources": coverage_sources,
            },
        )
        _write_json(run_dir / "source_hypotheses.json", {"segments": hypotheses})
        _write_json(run_dir / "fusion_decisions.json", {"segments": decisions})
        _write_json(run_dir / "timeline.json", {"schema_version": "2.0", "segments": timeline})
        _write_json(
            run_dir / "manifest.json",
            {
                "schema_version": "2.0",
                "run_id": run_id,
                "meeting_name": meeting_name,
                "status": "succeeded",
                "backend": "multi_source_transcript_fusion",
                "fusion_method_requested": requested_method,
                "fusion_method_used": actual_method,
                "identity_method_used": str(self.config.identity.get("method", "prototype_cosine")),
                "identity_threshold": self.config.identity.get("identity_threshold"),
                "identity_margin": self.config.identity.get("identity_margin"),
                "anonymous_cluster_threshold": self.config.identity.get(
                    "anonymous_cluster_threshold"
                ),
                "warnings": warnings,
                "speaker_profiles": [profile.speaker_id for profile in profiles],
                "models": {
                    "asr": f"{self.config.asr.model_id}@{self.config.asr.model_revision}",
                    "asr_decoding": {
                        "language": self.config.asr.language,
                        "max_new_tokens_per_second": self.config.asr.max_new_tokens_per_second,
                        "min_new_tokens": self.config.asr.min_new_tokens,
                        "max_new_tokens": self.config.asr.max_new_tokens,
                        "max_decode_attempts": self.config.asr.max_decode_attempts,
                    },
                    "speaker": (
                        f"{self.config.identity['model_id']}@"
                        f"{self.config.identity['model_revision']}"
                    ),
                    "vad": "silero_vad",
                    "speaker_turns": (
                        f"pyannote/segmentation-3.0@{self.config.models['segmentation_revision']}"
                    ),
                    "overlap_separation": "skipped",
                },
                "artifacts": [
                    "coverage.json",
                    "activity_regions.json",
                    "speaker_turns.json",
                    "source_hypotheses.json",
                    "fusion_decisions.json",
                    "timeline.json",
                    "aligned/",
                    "clips/evidence/",
                    "exports/",
                ],
            },
        )
        self._write_exports(run_dir, timeline)

    @staticmethod
    def _write_exports(run_dir: Path, timeline: list[dict[str, object]]) -> None:
        exports = run_dir / "exports"
        _write_json(exports / "result.json", {"schema_version": "2.0", "segments": timeline})
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
                    "fusion_method",
                    "primary_source_id",
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
                        segment.get("fusion_method") or "",
                        segment.get("selected_source_id") or "",
                    ]
                )
        with (exports / "result.txt").open("w", encoding="utf-8") as handle:
            for segment in timeline:
                text = (
                    "[Nói chồng: chưa xử lý]"
                    if segment.get("asr_status") == "not_run" and segment.get("speaker_count") == 2
                    else segment["text"]
                )
                handle.write(
                    f"[{float(str(segment['start_sec'])):.2f}-"
                    f"{float(str(segment['end_sec'])):.2f}] "
                    f"{segment.get('speaker_label') or 'Unknown'}: {text}\n"
                )
        with zipfile.ZipFile(exports / "result.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(run_dir.rglob("*")):
                if path.is_file() and path != exports / "result.zip":
                    archive.write(path, path.relative_to(run_dir))
