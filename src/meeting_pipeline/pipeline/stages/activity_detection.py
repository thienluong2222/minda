"""Multi-source VAD fusion and speech region activity detection."""

from __future__ import annotations

import math
import uuid
from typing import TYPE_CHECKING, Any

import numpy as np
import torch
from silero_vad import get_speech_timestamps, load_silero_vad

from meeting_pipeline.config import SegmentationConfig
from meeting_pipeline.domain.schemas import Interval
from meeting_pipeline.domain.transcription import SpeechRegion

if TYPE_CHECKING:
    from meeting_pipeline.adapters.pyannote_segmentation import PyannoteSegmentationAdapter
    from meeting_pipeline.pipeline.prototype import PreparedSource


def fuse_vad_intervals(
    source_intervals: dict[str, list[tuple[float, float]]],
    source_coverages: dict[str, tuple[float, float]],
    valid_source_ids: list[str],
    meeting_duration: float,
    merge_gap_ms: int = 400,
    minimum_speech_ms: int = 250,
    speech_pad_ms: int = 250,
    bin_sec: float = 0.01,
) -> list[SpeechRegion]:
    """Pure fusion and post-processing of multi-source VAD intervals.

    Operates on meeting-time intervals without loading any ML models.
    """
    if meeting_duration <= 0 or not valid_source_ids:
        return []

    bins = max(1, math.ceil(meeting_duration / bin_sec))
    speech_mask = np.zeros(bins, dtype=bool)

    # Union of speech across valid sources within their respective coverages
    for source_id in valid_source_ids:
        if source_id not in source_intervals or source_id not in source_coverages:
            continue
        cov_start, cov_end = source_coverages[source_id]
        for start_sec, end_sec in source_intervals[source_id]:
            # Clamp to source coverage and meeting duration
            eff_start = max(0.0, cov_start, start_sec)
            eff_end = min(meeting_duration, cov_end, end_sec)
            if eff_end > eff_start:
                s_idx = max(0, int(eff_start / bin_sec))
                e_idx = min(bins, math.ceil(eff_end / bin_sec))
                speech_mask[s_idx:e_idx] = True

    # Extract initial contiguous regions from mask
    min_speech_sec = minimum_speech_ms / 1000.0
    merge_gap_sec = merge_gap_ms / 1000.0
    pad_sec = speech_pad_ms / 1000.0

    raw_intervals: list[tuple[float, float]] = []
    in_speech = False
    start_bin = 0

    for idx in range(bins):
        if speech_mask[idx] and not in_speech:
            in_speech = True
            start_bin = idx
        elif not speech_mask[idx] and in_speech:
            in_speech = False
            raw_intervals.append((start_bin * bin_sec, idx * bin_sec))
    if in_speech:
        raw_intervals.append((start_bin * bin_sec, bins * bin_sec))

    # 1. Filter regions shorter than minimum_speech_ms
    filtered = [(s, e) for s, e in raw_intervals if (e - s) >= min_speech_sec - 1e-6]
    if not filtered:
        return []

    # 2. Merge regions separated by at most merge_gap_ms
    merged: list[tuple[float, float]] = []
    curr_start, curr_end = filtered[0]

    for next_start, next_end in filtered[1:]:
        if (next_start - curr_end) <= merge_gap_sec + 1e-6:
            curr_end = max(curr_end, next_end)
        else:
            merged.append((curr_start, curr_end))
            curr_start, curr_end = next_start, next_end
    merged.append((curr_start, curr_end))

    # 3. Apply speech padding and clamp to meeting bounds
    padded: list[tuple[float, float]] = []
    for s, e in merged:
        padded_s = max(0.0, s - pad_sec)
        padded_e = min(meeting_duration, e + pad_sec)
        if padded_e > padded_s:
            padded.append((padded_s, padded_e))

    # 4. Merge overlapping padded intervals if padding caused them to touch
    resolved: list[tuple[float, float]] = []
    if padded:
        c_s, c_e = padded[0]
        for n_s, n_e in padded[1:]:
            if n_s <= c_e:
                c_e = max(c_e, n_e)
            else:
                resolved.append((c_s, c_e))
                c_s, c_e = n_s, n_e
        resolved.append((c_s, c_e))

    # 5. Build SpeechRegion models with supporting source IDs and warnings
    speech_regions: list[SpeechRegion] = []
    for reg_start, reg_end in resolved:
        supporting_sources: list[str] = []
        coverage_sources: list[str] = []
        src_intervals: dict[str, Interval] = {}

        for source_id in valid_source_ids:
            cov_start, cov_end = source_coverages.get(source_id, (0.0, 0.0))
            overlap_start = max(reg_start, cov_start)
            overlap_end = min(reg_end, cov_end)

            if overlap_end > overlap_start:
                coverage_sources.append(source_id)
                src_intervals[source_id] = Interval(start_sec=overlap_start, end_sec=overlap_end)

                # Check if this source detected speech within this region
                detected_speech = False
                for s_start, s_end in source_intervals.get(source_id, []):
                    if min(reg_end, s_end) > max(reg_start, s_start):
                        detected_speech = True
                        break
                if detected_speech:
                    supporting_sources.append(source_id)

        warnings: list[str] = []
        if len(supporting_sources) == 1 and len(coverage_sources) > 1:
            warnings.append("single_source_vad_support")

        speech_regions.append(
            SpeechRegion(
                region_id=str(uuid.uuid4()),
                start_sec=round(reg_start, 4),
                end_sec=round(reg_end, 4),
                supporting_source_ids=supporting_sources,
                source_intervals=src_intervals,
                confidence=None,
                speaker_count=1,
                warnings=warnings,
            )
        )

    return speech_regions


class ActivityDetector:
    """Run Silero VAD on sources and fuse into unified meeting SpeechRegions."""

    def __init__(
        self,
        config: SegmentationConfig,
        sample_rate: int = 16000,
        pyannote_adapter: PyannoteSegmentationAdapter | None = None,
    ) -> None:
        self.config = config
        self.sample_rate = sample_rate
        self.pyannote_adapter = pyannote_adapter
        self._vad_model: Any = None

    def _get_vad_model(self) -> Any:
        if self._vad_model is None:
            self._vad_model = load_silero_vad(onnx=False)
        return self._vad_model

    def detect(
        self,
        sources: list[PreparedSource],
        meeting_duration: float,
    ) -> list[SpeechRegion]:
        """Detect multi-source activity and return meeting-time SpeechRegions."""
        valid_sources = [s for s in sources if s.alignment_status != "alignment_failed"]
        if not valid_sources or meeting_duration <= 0:
            return []

        vad_model = self._get_vad_model()
        source_intervals: dict[str, list[tuple[float, float]]] = {}
        source_coverages: dict[str, tuple[float, float]] = {}

        for source in valid_sources:
            cov_start = source.offset_sec
            cov_end = source.offset_sec + source.samples.size / self.sample_rate
            source_coverages[source.source_id] = (cov_start, cov_end)

            timestamps = get_speech_timestamps(
                torch.from_numpy(source.samples),
                vad_model,
                threshold=float(self.config.vad_threshold),
                sampling_rate=self.sample_rate,
                min_speech_duration_ms=int(self.config.minimum_speech_ms),
                min_silence_duration_ms=int(self.config.minimum_silence_ms),
                speech_pad_ms=int(self.config.speech_pad_ms),
            )

            intervals: list[tuple[float, float]] = []
            for ts in timestamps:
                start_sec = source.offset_sec + ts["start"] / self.sample_rate
                end_sec = source.offset_sec + ts["end"] / self.sample_rate
                intervals.append((start_sec, end_sec))
            source_intervals[source.source_id] = intervals

        # Fuse intervals using the pure algorithm
        regions = fuse_vad_intervals(
            source_intervals=source_intervals,
            source_coverages=source_coverages,
            valid_source_ids=[s.source_id for s in valid_sources],
            meeting_duration=meeting_duration,
            merge_gap_ms=int(self.config.merge_gap_ms),
            minimum_speech_ms=int(self.config.minimum_speech_ms),
            speech_pad_ms=int(self.config.speech_pad_ms),
        )

        # If Pyannote adapter is available, estimate speaker_count / overlap
        if self.pyannote_adapter is not None:
            self._estimate_overlap(regions, valid_sources, meeting_duration)

        return regions

    def _estimate_overlap(
        self,
        regions: list[SpeechRegion],
        valid_sources: list[PreparedSource],
        meeting_duration: float,
    ) -> None:
        """Score regions for simultaneous speakers using pyannote powerset evidence."""
        if not self.pyannote_adapter or not regions:
            return

        bin_sec = 0.05
        bins = math.ceil(meeting_duration / bin_sec)
        per_source: list[np.ndarray] = []
        chunk_step = float(self.config.step_seconds)

        for source in valid_sources:
            try:
                scores = self.pyannote_adapter.segment_file(source.analysis_path)
            except Exception:
                continue

            counts = np.zeros(bins, dtype=np.float32)
            votes = np.zeros(bins, dtype=np.float32)
            frame_step = 0.016875
            frame_duration = 0.0619375

            for chunk_index, chunk in enumerate(scores.data):
                chunk_start = chunk_index * chunk_step + source.offset_sec
                active = np.sum(chunk >= 0.5, axis=1)
                for frame_index, count in enumerate(active):
                    time_sec = chunk_start + frame_index * frame_step + frame_duration / 2
                    source_end_sec = source.offset_sec + source.samples.size / self.sample_rate
                    if not source.offset_sec <= time_sec < source_end_sec:
                        continue
                    bin_index = int(time_sec / bin_sec)
                    if 0 <= bin_index < bins:
                        counts[bin_index] += min(2, int(count))
                        votes[bin_index] += 1

            per_source.append(np.divide(counts, votes, out=np.zeros_like(counts), where=votes > 0))

        if not per_source:
            return

        stacked = np.stack(per_source)
        ordered = np.sort(stacked, axis=0)
        evidence = ordered[-2:].mean(axis=0) if stacked.shape[0] > 1 else ordered[-1]

        for region in regions:
            s_idx = max(0, int(region.start_sec / bin_sec))
            e_idx = min(bins, math.ceil(region.end_sec / bin_sec))
            if e_idx > s_idx:
                reg_evidence = float(np.mean(evidence[s_idx:e_idx]))
                if reg_evidence >= 1.5:
                    region.speaker_count = 2
                else:
                    region.speaker_count = 1
