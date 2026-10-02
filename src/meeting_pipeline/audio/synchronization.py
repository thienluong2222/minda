"""Multi-device audio synchronization and shared VAD segmentation.

Specification: Section 8 & 9 of docs/PLAN_VIVOS_SYNTHETIC_PIPELINE.md and
WP1 of PLAN_VAD_SPEAKER_ASR_MULTI_SOURCE_2026-10-03.md.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import torch
from silero_vad import get_speech_timestamps, load_silero_vad

from meeting_pipeline.adapters.pyannote_segmentation import PyannoteSegmentationAdapter
from meeting_pipeline.domain.contracts import MeetingSegment, VadConfig
from meeting_pipeline.pipeline.stages.activity_detection import fuse_vad_intervals
from meeting_pipeline.pipeline.stages.shared_segmentation import run_shared_pyannote_segmentation
from meeting_pipeline.pipeline.stages.synchronize import estimate_offset
from meeting_pipeline.simulation.device import apply_clock_drift, apply_start_offset

logger = logging.getLogger(__name__)


def select_reference_source(
    audio_signals: dict[str, np.ndarray[Any, np.dtype[np.float32]]],
) -> str:
    """Select the best reference device by RMS signal energy and non-silence ratio."""
    best_source = ""
    best_score = -1.0

    for src_id, sig in audio_signals.items():
        if len(sig) == 0:
            continue
        rms = float(np.sqrt(np.mean(sig**2)))
        non_silent_ratio = float(np.mean(np.abs(sig) > 0.01))
        score = rms * (0.5 + non_silent_ratio)
        if score > best_score:
            best_score = score
            best_source = src_id

    return best_source or next(iter(audio_signals.keys()))


def _estimate_windowed_drift(
    ref_signal: np.ndarray[Any, np.dtype[np.float32]],
    source_signal: np.ndarray[Any, np.dtype[np.float32]],
    sample_rate: int,
    base_offset_sec: float,
    window_sec: float = 8.0,
    step_sec: float = 15.0,
) -> tuple[float, float, str]:
    """Measure offset at multiple common windows to detect clock drift and stability."""
    total_sec = min(len(ref_signal), len(source_signal)) / sample_rate
    if total_sec < 25.0:
        return 0.0, 0.5, "aligned"

    window_samples = int(window_sec * sample_rate)
    step_samples = int(step_sec * sample_rate)

    time_points: list[float] = []
    measured_offsets: list[float] = []

    pos = 0
    while pos + window_samples <= min(len(ref_signal), len(source_signal)):
        sub_ref = ref_signal[pos : pos + window_samples]
        sub_src = source_signal[pos : pos + window_samples]

        # Only measure if both windows have substantial signal variance
        if np.std(sub_ref) > 1e-4 and np.std(sub_src) > 1e-4:
            try:
                est = estimate_offset(
                    reference=sub_ref,
                    source=sub_src,
                    sample_rate=sample_rate,
                    envelope_rate_hz=100,
                    max_offset_seconds=5.0,
                )
                time_points.append(pos / sample_rate)
                measured_offsets.append(float(est.mapping.offset_sec or 0.0))
            except Exception:
                pass
        pos += step_samples

    if len(measured_offsets) < 3:
        return 0.0, 5.0, "drift_unresolved"

    t_arr = np.array(time_points, dtype=np.float64)
    off_arr = np.array(measured_offsets, dtype=np.float64)

    # Simple median absolute deviation filter for outlier rejection
    med_off = np.median(off_arr)
    mad = np.median(np.abs(off_arr - med_off)) + 1e-6
    inliers = np.abs(off_arr - med_off) <= 3.0 * mad

    if np.sum(inliers) < 3:
        return 0.0, float(mad * 1000.0), "drift_unresolved"

    t_in = t_arr[inliers]
    off_in = off_arr[inliers]

    # Linear fit: offset(t) = slope * t + intercept
    A = np.vstack([t_in, np.ones_like(t_in)]).T
    slope, intercept = np.linalg.lstsq(A, off_in, rcond=None)[0]
    drift_ppm = float(slope * 1e6)

    residuals = off_in - (slope * t_in + intercept)
    residual_ms = float(np.std(residuals) * 1000.0)

    status = "aligned" if residual_ms < 20.0 else "drift_unresolved"
    return drift_ppm, residual_ms, status


def synchronize_multi_source_audio(
    audio_signals: dict[str, np.ndarray[Any, np.dtype[np.float32]]],
    sample_rate: int = 16000,
    reference_source_id: str | None = None,
    allow_drift: bool = True,
) -> tuple[
    dict[str, np.ndarray[Any, np.dtype[np.float32]]],
    dict[str, dict[str, Any]],
    str,
]:
    """Synchronize multiple audio sources to a common timeline.

    Returns:
    - aligned_signals: dict[source_id, 1D float32 array] of equal length.
    - sync_metadata: dict[source_id, {offset_sec, drift_ppm, residual_ms, status}].
    - reference_source_id: the chosen reference device.
    """
    ref_id = reference_source_id or select_reference_source(audio_signals)
    ref_signal = audio_signals[ref_id]

    aligned_signals: dict[str, np.ndarray[Any, np.dtype[np.float32]]] = {}
    sync_metadata: dict[str, dict[str, Any]] = {}

    max_len = 0

    for src_id, sig in audio_signals.items():
        if src_id == ref_id:
            aligned_signals[src_id] = sig.copy()
            sync_metadata[src_id] = {
                "offset_sec": 0.0,
                "drift_ppm": 0.0,
                "residual_ms": 0.0,
                "status": "aligned",
            }
            max_len = max(max_len, len(sig))
            continue

        try:
            # Estimate coarse offset using log-energy envelope correlation
            align_est = estimate_offset(
                reference=ref_signal,
                source=sig,
                sample_rate=sample_rate,
                envelope_rate_hz=100,
                max_offset_seconds=10.0,
            )
            offset_sec = float(align_est.mapping.offset_sec or 0.0)
            residual_ms = float(align_est.residual_sec * 1000.0)
            status = "aligned"
        except Exception as exc:
            logger.warning("Alignment correlation failed for %s: %s; marked failed", src_id, exc)
            offset_sec = 0.0
            residual_ms = 999.0
            status = "alignment_failed"

        drift_ppm = 0.0
        if status != "alignment_failed" and allow_drift:
            meas_drift, win_res_ms, win_status = _estimate_windowed_drift(
                ref_signal, sig, sample_rate, offset_sec
            )
            if abs(meas_drift) > 5.0 and win_res_ms < 25.0:
                drift_ppm = meas_drift
                residual_ms = max(residual_ms, win_res_ms)
                status = win_status

        # Apply alignment shift
        shifted = apply_start_offset(sig, offset_sec, sample_rate=sample_rate)
        if abs(drift_ppm) > 0.01:
            shifted = apply_clock_drift(shifted, -drift_ppm)

        aligned_signals[src_id] = shifted
        sync_metadata[src_id] = {
            "offset_sec": offset_sec,
            "drift_ppm": drift_ppm,
            "residual_ms": residual_ms,
            "status": status,
        }
        max_len = max(max_len, len(shifted))

    # Pad all signals to max_len so they have identical timeline
    for src_id, sig in aligned_signals.items():
        if len(sig) < max_len:
            pad = np.zeros(max_len - len(sig), dtype=np.float32)
            aligned_signals[src_id] = np.concatenate([sig, pad])

    return aligned_signals, sync_metadata, ref_id


def extract_shared_meeting_segments(
    aligned_signals: dict[str, np.ndarray[Any, np.dtype[np.float32]]],
    vad_config: VadConfig,
    meeting_id: str,
    sample_rate: int = 16000,
    backend: str = "silero",
    pyannote_adapter: PyannoteSegmentationAdapter | None = None,
    aligned_paths: dict[str, Path] | None = None,
    sync_metadata: dict[str, dict[str, Any]] | None = None,
    run_dir: Path | None = None,
) -> list[MeetingSegment]:
    """Run VAD on all aligned sources and fuse into unified meeting segments.

    Supports Option B (pyannote) or Option A (silero) as baseline.
    """
    if backend == "pyannote" and pyannote_adapter is not None and aligned_paths is not None:
        dur_sec = max((len(s) for s in aligned_signals.values()), default=0) / sample_rate
        segments, _ = run_shared_pyannote_segmentation(
            aligned_paths=aligned_paths,
            adapter=pyannote_adapter,
            meeting_duration_sec=dur_sec,
            vad_config=vad_config,
            meeting_id=meeting_id,
            sync_metadata=sync_metadata,
            run_dir=run_dir,
        )
        return segments

    # Baseline Option A: Silero VAD
    vad_model = load_silero_vad()
    source_intervals: dict[str, list[tuple[float, float]]] = {}
    source_coverages: dict[str, tuple[float, float]] = {}

    meeting_duration_sec = 0.0

    valid_sources: list[str] = []
    for src_id, sig in aligned_signals.items():
        if sync_metadata and sync_metadata.get(src_id, {}).get("status") == "alignment_failed":
            continue
        valid_sources.append(src_id)
        dur_sec = len(sig) / sample_rate
        meeting_duration_sec = max(meeting_duration_sec, dur_sec)
        source_coverages[src_id] = (0.0, dur_sec)

        tensor_audio = torch.from_numpy(sig).float()

        raw_timestamps = get_speech_timestamps(
            tensor_audio,
            vad_model,
            sampling_rate=sample_rate,
            threshold=vad_config.threshold,
            min_speech_duration_ms=round(vad_config.min_speech_sec * 1000),
            min_silence_duration_ms=round(vad_config.min_silence_sec * 1000),
            speech_pad_ms=round(vad_config.padding_sec * 1000),
        )

        intervals: list[tuple[float, float]] = []
        for ts in raw_timestamps:
            start_s = ts["start"] / sample_rate
            end_s = ts["end"] / sample_rate
            intervals.append((start_s, end_s))

        source_intervals[src_id] = intervals

    fused_regions = fuse_vad_intervals(
        source_intervals=source_intervals,
        source_coverages=source_coverages,
        valid_source_ids=valid_sources or list(aligned_signals.keys()),
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
                        schema_version="1.0",
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
                    schema_version="1.0",
                    meeting_id=meeting_id,
                    segment_id=f"seg_{seg_idx:04d}",
                    start_sec=round(start_s, 3),
                    end_sec=round(end_s, 3),
                    overlap=False,
                )
            )
            seg_idx += 1

    return meeting_segments
