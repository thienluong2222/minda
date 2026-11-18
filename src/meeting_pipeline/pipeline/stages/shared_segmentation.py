"""Shared Pyannote segmentation VAD (Option B) and turn evidence pipeline.

Implements single-inference-per-source VAD and speaker turn detection by reusing
the cached 3-channel local multilabel segmentation outputs from pyannote/segmentation-3.0.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from meeting_pipeline.adapters.pyannote_segmentation import (
    PyannoteSegmentationAdapter,
    SegmentationResult,
)
from meeting_pipeline.audio.coverage import intersect_recorded, recorded_intervals
from meeting_pipeline.domain.contracts import MeetingSegment, VadConfig
from meeting_pipeline.pipeline.stages.activity_detection import fuse_vad_intervals


def compute_pyannote_activity_curve(
    result: SegmentationResult,
    meeting_duration_sec: float,
    bin_sec: float = 0.02,
    offset_sec: float = 0.0,
) -> np.ndarray[Any, np.dtype[np.float32]]:
    """Convert pyannote chunk multilabel predictions into a continuous 1D speech activity curve.

    Each chunk contains local multilabel probabilities in [0, 1] across 3 channels.
    Frame activity is taken as max across channels. Overlapping chunk predictions
    are merged with trapezoidal weighting to de-emphasize less reliable chunk boundaries.
    """
    num_bins = max(1, math.ceil(meeting_duration_sec / bin_sec))
    activity_sum = np.zeros(num_bins, dtype=np.float32)
    weight_sum = np.zeros(num_bins, dtype=np.float32)

    data = result.data
    if data.ndim != 3 or data.shape[0] == 0:
        return activity_sum

    chunk_duration = float(result.sliding_window.duration)
    step_seconds = float(result.sliding_window.step)
    num_chunks, num_frames, _ = data.shape
    frame_step = chunk_duration / max(1, num_frames)

    # Max across local speaker channels: represents presence of at least one speaker
    channel_max = np.max(data, axis=2)  # shape: (num_chunks, num_frames)

    for chunk_idx in range(num_chunks):
        chunk_start = chunk_idx * step_seconds + offset_sec
        frames = channel_max[chunk_idx]

        for frame_idx, act in enumerate(frames):
            rel_t = (frame_idx + 0.5) * frame_step
            abs_start = chunk_start + frame_idx * frame_step
            abs_end = chunk_start + (frame_idx + 1) * frame_step
            if abs_start >= meeting_duration_sec or abs_end <= 0.0:
                continue

            s_bin = max(0, int(abs_start / bin_sec))
            e_bin = min(num_bins, int(np.ceil(abs_end / bin_sec)))
            if e_bin <= s_bin:
                e_bin = min(num_bins, s_bin + 1)

            # Trapezoidal taper for 1.25s margins of 10s chunk
            margin = 1.25
            if rel_t < margin:
                w = max(0.1, rel_t / margin)
            elif rel_t > chunk_duration - margin:
                w = max(0.1, (chunk_duration - rel_t) / margin)
            else:
                w = 1.0

            for b in range(s_bin, e_bin):
                activity_sum[b] += float(act) * w
                weight_sum[b] += w

    return np.divide(
        activity_sum,
        weight_sum,
        out=np.zeros_like(activity_sum),
        where=weight_sum > 0,
    )


def extract_pyannote_vad_intervals(
    activity_curve: np.ndarray[Any, np.dtype[np.float32]],
    bin_sec: float = 0.02,
    threshold: float = 0.5,
    min_speech_ms: int = 250,
    merge_gap_ms: int = 400,
    speech_pad_ms: int = 250,
    meeting_duration_sec: float = 0.0,
) -> list[tuple[float, float]]:
    """Threshold continuous activity curve into speech intervals with smoothing."""
    num_bins = len(activity_curve)
    if num_bins == 0:
        return []

    effective_dur = meeting_duration_sec if meeting_duration_sec > 0 else num_bins * bin_sec
    active_mask = activity_curve >= threshold

    # 1. Identify raw active contiguous intervals
    raw_intervals: list[tuple[float, float]] = []
    in_speech = False
    start_bin = 0

    for idx in range(num_bins):
        if active_mask[idx] and not in_speech:
            in_speech = True
            start_bin = idx
        elif not active_mask[idx] and in_speech:
            in_speech = False
            raw_intervals.append((start_bin * bin_sec, idx * bin_sec))
    if in_speech:
        raw_intervals.append((start_bin * bin_sec, num_bins * bin_sec))

    if not raw_intervals:
        return []

    # 2. Merge close intervals
    merge_gap_sec = merge_gap_ms / 1000.0
    merged: list[tuple[float, float]] = []
    curr_s, curr_e = raw_intervals[0]
    for n_s, n_e in raw_intervals[1:]:
        if n_s - curr_e <= merge_gap_sec + 1e-6:
            curr_e = max(curr_e, n_e)
        else:
            merged.append((curr_s, curr_e))
            curr_s, curr_e = n_s, n_e
    merged.append((curr_s, curr_e))

    # 3. Filter short intervals
    min_speech_sec = min_speech_ms / 1000.0
    filtered = [(s, e) for s, e in merged if (e - s) >= min_speech_sec - 1e-6]
    if not filtered:
        return []

    # 4. Speech padding
    pad_sec = speech_pad_ms / 1000.0
    padded: list[tuple[float, float]] = []
    for s, e in filtered:
        p_s = max(0.0, s - pad_sec)
        p_e = min(effective_dur, e + pad_sec)
        if p_e > p_s:
            padded.append((p_s, p_e))

    # 5. Merge touched intervals due to padding
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

    return resolved


def run_shared_pyannote_segmentation(
    aligned_paths: dict[str, Path],
    adapter: PyannoteSegmentationAdapter,
    meeting_duration_sec: float,
    vad_config: VadConfig,
    meeting_id: str,
    sync_metadata: dict[str, dict[str, Any]] | None = None,
    valid_source_ids: list[str] | None = None,
    run_dir: Path | None = None,
    bin_sec: float = 0.02,
) -> tuple[list[MeetingSegment], dict[str, SegmentationResult]]:
    """Run pyannote segmentation once per source and extract unified meeting segments.

    Option B: Single inference per source cached for both VAD and turn detection.
    """
    if not aligned_paths or meeting_duration_sec <= 0:
        return [], {}

    # Filter out sources that failed alignment
    active_sources = list(aligned_paths.keys())
    if valid_source_ids is not None:
        active_sources = [sid for sid in active_sources if sid in valid_source_ids]
    if sync_metadata is not None:
        active_sources = [
            sid
            for sid in active_sources
            if sync_metadata.get(sid, {}).get("status") != "alignment_failed"
        ]

    if not active_sources:
        return [], {}

    segmentation_results: dict[str, SegmentationResult] = {}
    source_intervals: dict[str, list[tuple[float, float]]] = {}
    source_coverages: dict[str, tuple[float, float]] = {}

    for source_id in active_sources:
        path = aligned_paths[source_id]
        seg_res = adapter.segment_file(path, source_id=source_id)
        segmentation_results[source_id] = seg_res

        if run_dir is not None:
            npz_path = run_dir / "segmentation" / f"{source_id}.npz"
            adapter.save_npz(npz_path, seg_res)

        # Aligned audio coverage
        coverage = (sync_metadata or {}).get(source_id, {}).get("valid_coverage_interval")
        source_coverages[source_id] = (
            (float(coverage[0]), float(coverage[1])) if coverage else (0.0, meeting_duration_sec)
        )

        # Compute activity curve from pyannote multi-label predictions
        curve = compute_pyannote_activity_curve(
            seg_res,
            meeting_duration_sec=meeting_duration_sec,
            bin_sec=bin_sec,
            offset_sec=0.0,  # Audio is already aligned on meeting clock
        )

        intervals = extract_pyannote_vad_intervals(
            curve,
            bin_sec=bin_sec,
            threshold=float(vad_config.threshold),
            min_speech_ms=round(vad_config.min_speech_sec * 1000),
            merge_gap_ms=round(vad_config.merge_gap_sec * 1000),
            speech_pad_ms=round(vad_config.padding_sec * 1000),
            meeting_duration_sec=meeting_duration_sec,
        )
        source_intervals[source_id] = intersect_recorded(
            intervals,
            recorded_intervals(
                (sync_metadata or {}).get(source_id, {}), (0.0, meeting_duration_sec)
            ),
        )

    # Multi-source VAD fusion
    fused_regions = fuse_vad_intervals(
        source_intervals=source_intervals,
        source_coverages=source_coverages,
        valid_source_ids=active_sources,
        meeting_duration=meeting_duration_sec,
        merge_gap_ms=round(vad_config.merge_gap_sec * 1000),
        minimum_speech_ms=round(vad_config.min_speech_sec * 1000),
        speech_pad_ms=round(vad_config.padding_sec * 1000),
    )

    meeting_segments: list[MeetingSegment] = []
    seg_idx = 0

    for reg in fused_regions:
        start_s = reg.start_sec
        end_s = reg.end_sec
        dur = end_s - start_s

        if dur > vad_config.max_segment_sec:
            sub_start = start_s
            while sub_start < end_s:
                sub_end = min(end_s, sub_start + vad_config.max_segment_sec)
                meeting_segments.append(
                    MeetingSegment(
                        schema_version="2.0",
                        meeting_id=meeting_id,
                        segment_id=f"seg_{seg_idx:04d}",
                        start_sec=round(sub_start, 3),
                        end_sec=round(sub_end, 3),
                        overlap=False,
                    )
                )
                seg_idx += 1
                sub_start = sub_end
        else:
            meeting_segments.append(
                MeetingSegment(
                    schema_version="2.0",
                    meeting_id=meeting_id,
                    segment_id=f"seg_{seg_idx:04d}",
                    start_sec=round(start_s, 3),
                    end_sec=round(end_s, 3),
                    overlap=False,
                )
            )
            seg_idx += 1

    return meeting_segments, segmentation_results
