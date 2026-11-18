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
from meeting_pipeline.simulation.device import apply_clock_drift

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
    envelope_rate_hz: int = 100,
    minimum_common_speech_seconds: float = 3.0,
    minimum_drift_inliers: int = 3,
) -> tuple[float, float, str]:
    """Measure local residual offsets in corresponding (coarse-aligned) windows.

    Short or silent recordings do not prove zero drift. The activity check here is
    signal variance, not a speech detector; speech-aware anchors belong to stage 3.
    """
    window_samples = int(window_sec * sample_rate)
    step_samples = max(1, round(step_sec * sample_rate))
    base_samples = round(base_offset_sec * sample_rate)
    source_start = max(0, -base_samples)
    source_end = min(len(source_signal), len(ref_signal) - base_samples)
    if window_samples < 1 or (source_end - source_start) / sample_rate < max(
        window_sec, minimum_common_speech_seconds
    ):
        return 0.0, 999.0, "drift_unresolved"

    time_points: list[float] = []
    measured_offsets: list[float] = []

    pos = source_start
    while pos + window_samples <= source_end:
        ref_pos = pos + base_samples
        sub_ref = ref_signal[ref_pos : ref_pos + window_samples]
        sub_src = source_signal[pos : pos + window_samples]

        # Only measure if both windows have substantial signal variance
        if np.std(sub_ref) > 1e-4 and np.std(sub_src) > 1e-4:
            try:
                est = estimate_offset(
                    reference=sub_ref,
                    source=sub_src,
                    sample_rate=sample_rate,
                    envelope_rate_hz=envelope_rate_hz,
                    max_offset_seconds=min(1.0, window_sec / 4),
                )
                time_points.append(pos / sample_rate)
                measured_offsets.append(
                    base_samples / sample_rate + float(est.mapping.offset_sec or 0.0)
                )
            except Exception:
                pass
        pos += step_samples

    if len(measured_offsets) < minimum_drift_inliers:
        return 0.0, 999.0, "drift_unresolved"

    t_arr = np.array(time_points, dtype=np.float64)
    off_arr = np.array(measured_offsets, dtype=np.float64)

    # Simple median absolute deviation filter for outlier rejection
    med_off = np.median(off_arr)
    mad = np.median(np.abs(off_arr - med_off)) + 1e-6
    inliers = np.abs(off_arr - med_off) <= 3.0 * mad

    if np.sum(inliers) < minimum_drift_inliers:
        return 0.0, 999.0, "drift_unresolved"

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
    *,
    envelope_rate_hz: int = 100,
    max_offset_seconds: float = 120.0,
    fine_window_seconds: float = 8.0,
    long_recording_step_seconds: float = 30.0,
    minimum_common_speech_seconds: float = 3.0,
    minimum_drift_inliers: int = 3,
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

    ``offset_sec`` retains the estimate relative to the original reference for
    diagnostics. Use ``timeline_offset_sec`` and ``time_scale`` for the shifted
    output clock; ``origin_shift_sec`` explains the change of meeting origin.
    """
    if not audio_signals or sample_rate <= 0:
        raise ValueError("At least one source and a positive sample rate are required")
    if any(sig.ndim != 1 or not len(sig) for sig in audio_signals.values()):
        raise ValueError("Sources must be nonempty mono waveforms")
    ref_id = reference_source_id or select_reference_source(audio_signals)
    ref_signal = audio_signals[ref_id]

    aligned_signals: dict[str, np.ndarray[Any, np.dtype[np.float32]]] = {}
    sync_metadata: dict[str, dict[str, Any]] = {}

    # First estimate on source-local clocks. Do not trim negative offsets.
    for src_id, sig in audio_signals.items():
        if src_id == ref_id:
            sync_metadata[src_id] = {
                "offset_sec": 0.0,
                "drift_ppm": 0.0,
                "residual_ms": 0.0,
                "status": "reference",
                "coarse_residual_ms": 0.0,
                "drift_status": "reference",
            }
            continue

        try:
            # Estimate coarse offset using log-energy envelope correlation
            align_est = estimate_offset(
                reference=ref_signal,
                source=sig,
                sample_rate=sample_rate,
                envelope_rate_hz=envelope_rate_hz,
                max_offset_seconds=max_offset_seconds,
            )
            offset_sec = float(align_est.mapping.offset_sec or 0.0)
            residual_ms = float(align_est.residual_sec * 1000.0)
            status = "drift_unresolved"
        except Exception as exc:
            logger.warning("Alignment correlation failed for %s: %s; marked failed", src_id, exc)
            offset_sec = 0.0
            residual_ms = 999.0
            status = "alignment_failed"

        drift_ppm = 0.0
        coarse_residual_ms = residual_ms
        drift_residual_ms = None
        drift_status = "not_measured"
        if status != "alignment_failed" and allow_drift:
            meas_drift, win_res_ms, win_status = _estimate_windowed_drift(
                ref_signal,
                sig,
                sample_rate,
                offset_sec,
                window_sec=fine_window_seconds,
                step_sec=long_recording_step_seconds,
                envelope_rate_hz=envelope_rate_hz,
                minimum_common_speech_seconds=minimum_common_speech_seconds,
                minimum_drift_inliers=minimum_drift_inliers,
            )
            drift_status = win_status
            status = win_status
            if win_status == "aligned" and np.isfinite(meas_drift) and win_res_ms < 20.0:
                drift_ppm = meas_drift
                residual_ms = max(residual_ms, win_res_ms)
                drift_residual_ms = win_res_ms
            else:
                status = "drift_unresolved"
                residual_ms = 999.0
        elif status != "alignment_failed":
            residual_ms = 999.0
        sync_metadata[src_id] = {
            "offset_sec": offset_sec,
            "drift_ppm": drift_ppm,
            "residual_ms": residual_ms,
            "status": status,
            "coarse_residual_ms": coarse_residual_ms,
            "drift_status": drift_status,
            "drift_residual_ms": drift_residual_ms,
        }

    # Shift the origin of the entire meeting, including the reference. This keeps
    # unique early speech when the selected reference began recording later.
    origin_shift = -min(
        float(meta["offset_sec"])
        for meta in sync_metadata.values()
        if meta["status"] != "alignment_failed"
    )
    max_len = 0
    for src_id, sig in audio_signals.items():
        meta = sync_metadata[src_id]
        scale = 1.0 + float(meta["drift_ppm"]) * 1e-6
        if not np.isfinite(scale) or scale <= 0:
            raise ValueError("Invalid measured clock scale")
        corrected = apply_clock_drift(sig, (1.0 / scale - 1.0) * 1e6)
        start = max(0, round((float(meta["offset_sec"]) + origin_shift) * sample_rate))
        aligned_signals[src_id] = np.pad(corrected, (start, 0))
        meta.update(
            origin_shift_sec=origin_shift,
            timeline_offset_sec=start / sample_rate,
            time_scale=scale,
            coverage_confirmed=meta["status"] in {"reference", "aligned"},
            valid_coverage_interval=[start / sample_rate, (start + len(corrected)) / sample_rate],
        )
        max_len = max(max_len, len(aligned_signals[src_id]))

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
        coverage = (sync_metadata or {}).get(src_id, {}).get("valid_coverage_interval")
        source_coverages[src_id] = (
            (float(coverage[0]), float(coverage[1])) if coverage else (0.0, dur_sec)
        )

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
