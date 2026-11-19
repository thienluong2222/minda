"""Multi-microphone delay-and-sum with GCC-PHAT local tracking for ASR chunks."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.fft import irfft, next_fast_len, rfft, rfftfreq

from meeting_pipeline.audio.coverage import recorded_intervals

ASR_AUDIO_INPUT_ID = "prepared-mono"
AUDIO_FUSION_METHOD = "AUDIO_DELAY_AND_SUM"
FloatAudio = NDArray[np.float32]


def _window_lag(
    reference: FloatAudio, secondary: FloatAudio, sample_rate: int
) -> tuple[int, float, float] | None:
    """Estimate local integer delay (lag, bandpass_similarity, peak_ratio).

    Positive lag means the secondary signal arrives later than the reference.
    """
    limit = round(0.04 * sample_rate)
    if limit < 4 or len(reference) <= limit:
        return None
    n_fft = next_fast_len(2 * len(reference) - 1)
    window = np.hanning(len(reference))
    fa = rfft((reference - np.mean(reference)) * window, n_fft)
    fb = rfft((secondary - np.mean(secondary)) * window, n_fft)
    cross = fb * fa.conj()
    frequencies = rfftfreq(n_fft, 1 / sample_rate)
    band = (frequencies >= 150) & (frequencies <= min(6500, sample_rate / 2))
    phat = np.where(band, cross / np.maximum(np.abs(cross), 1e-12), 0)
    correlation = irfft(phat, n_fft)
    search = np.r_[correlation[-limit:], correlation[: limit + 1]]
    index = int(np.argmax(search))
    lag = index - limit
    peak_val = float(search[index])
    if abs(lag) == limit or peak_val <= 0:
        return None
    other = np.abs(np.r_[search[: max(0, index - 2)], search[index + 3 :]])
    ratio = peak_val / max(float(np.max(other, initial=1e-12)), 1e-12)
    if ratio < 1.25:
        return None

    band_a = irfft(np.where(band, fa, 0), n_fft)[: len(reference)]
    band_b = irfft(np.where(band, fb, 0), n_fft)[: len(secondary)]
    left, right = max(0, -lag), min(len(band_a), len(band_a) - lag)
    if right <= left:
        return None
    first, second = band_a[left:right], band_b[left + lag : right + lag]
    norm = float(np.linalg.norm(first) * np.linalg.norm(second))
    similarity = float(np.dot(first, second) / norm) if norm else 0.0
    if similarity < 0.05:
        return None
    return lag, similarity, ratio


def _stable_lag_trajectory(
    reference: FloatAudio, secondary: FloatAudio, sample_rate: int
) -> tuple[float, float, float] | None:
    """Fit a linear local delay trajectory ``lag(t) = lag0 + slope * t`` across active frames.

    Tolerates residual sample-rate offset (SRO) across real devices and isolated
    quiet/noisy frames while rejecting uncorrelated channels.
    """
    if len(reference) < round(0.35 * sample_rate):
        return None
    frame = min(len(reference), sample_rate)
    starts = sorted(
        {*range(0, len(reference) - frame + 1, max(1, frame // 2)), len(reference) - frame}
    )
    peak_rms = max(float(np.linalg.norm(reference[start : start + frame])) for start in starts)
    if peak_rms <= 1e-6:
        return None
    active_starts = [
        start
        for start in starts
        if np.linalg.norm(reference[start : start + frame]) >= 0.25 * peak_rms
        and np.linalg.norm(secondary[start : start + frame]) > 1e-6
    ]
    if not active_starts:
        return None

    estimates: list[tuple[float, int, float, float]] = []
    for start in active_starts:
        estimate = _window_lag(
            reference[start : start + frame],
            secondary[start : start + frame],
            sample_rate,
        )
        if estimate is not None:
            lag, sim, ratio = estimate
            estimates.append((start + frame / 2.0, lag, sim, ratio))

    required = 1 if len(active_starts) <= 2 else max(2, len(active_starts) // 2)
    if len(estimates) < required:
        return None

    if len(estimates) == 1:
        _, lag, sim, ratio = estimates[0]
        if ratio < 1.45 or sim < 0.15:
            return None
        return float(lag), 0.0, sim

    ts = np.array([row[0] for row in estimates], dtype=np.float64)
    lags = np.array([row[1] for row in estimates], dtype=np.float64)
    sims = np.array([row[2] for row in estimates], dtype=np.float64)

    if len(estimates) == 2:
        dt = float(ts[1] - ts[0])
        slope = float((lags[1] - lags[0]) / dt) if dt > 0 else 0.0
        lag0 = float(lags[0] - slope * ts[0])
        if abs(slope) * sample_rate > 4.0 or float(np.median(sims)) < 0.12:
            return None
        return lag0, slope, float(np.min(sims))

    # Theil-Sen median pairwise slope resists speaker pauses/transient outlier frames.
    pair_slopes = [
        (lags[j] - lags[i]) / (ts[j] - ts[i])
        for i in range(len(ts))
        for j in range(i + 1, len(ts))
        if ts[j] > ts[i]
    ]
    if not pair_slopes:
        return None
    slope_ts = float(np.median(pair_slopes))
    lag0_ts = float(np.median(lags - slope_ts * ts))
    tolerance = max(2.5, 0.0002 * sample_rate)
    inliers = np.abs(lags - (lag0_ts + slope_ts * ts)) <= tolerance
    if int(np.sum(inliers)) < max(2, len(active_starts) // 2):
        return None

    t_in, lag_in, sim_in = ts[inliers], lags[inliers], sims[inliers]
    design = np.vstack([t_in, np.ones_like(t_in)]).T
    slope, lag0 = np.linalg.lstsq(design, lag_in, rcond=None)[0]
    slope_f, lag0_f = float(slope), float(lag0)
    max_resid = float(np.max(np.abs(lag_in - (lag0_f + slope_f * t_in))))
    if abs(slope_f) * sample_rate > 4.0 or max_resid > tolerance:
        return None
    if float(np.median(sim_in)) < 0.12 and float(np.max(sim_in)) < 0.18:
        return None
    return lag0_f, slope_f, float(np.min(sim_in))


def _sample_shifted(
    signal: FloatAudio, positions: NDArray[np.float64], slope: float, lag0: float
) -> FloatAudio:
    if abs(slope) < 1e-9 and abs(lag0 - round(lag0)) < 1e-6:
        start = round(float(positions[0]))
        return signal[start : start + len(positions)]
    grid = np.arange(len(signal), dtype=np.float64)
    return np.interp(positions, grid, signal).astype(np.float32, copy=False)


def fuse_sources(
    sources: Sequence[tuple[str, FloatAudio, dict[str, Any], float]],
    *,
    clip_start: int,
    core: tuple[int, int],
    sample_rate: int,
) -> tuple[FloatAudio, dict[str, Any]]:
    """Fuse two or more coarse-aligned microphones on one turn using reference clock."""
    if not sources:
        raise ValueError("At least one audio source is required")
    ref_id, reference, reference_coverage, ref_score = sources[0]
    ref_score = max(float(ref_score), 1e-4)
    a, b = core[0] - clip_start, core[1] - clip_start
    if (
        len(sources) < 2
        or a < 0
        or b > len(reference)
        or any(len(sig) != len(reference) for _, sig, _, _ in sources[1:])
    ):
        return reference, {"fallback_reason": "incomplete_chunk"}

    fallback = (clip_start / sample_rate, (clip_start + len(reference)) / sample_rate)
    ref_intervals = recorded_intervals(reference_coverage, fallback)

    numerator = np.full(len(reference), ref_score, dtype=np.float64) * reference
    denominator = np.full(len(reference), ref_score, dtype=np.float64)
    weight_traces: dict[str, NDArray[np.float64]] = {
        ref_id: np.full(len(reference), ref_score, dtype=np.float64)
    }
    accepted: dict[str, dict[str, Any]] = {}
    rejected: dict[str, str] = {}

    for sec_id, secondary, secondary_coverage, sec_score in sources[1:]:
        estimated = _stable_lag_trajectory(reference[a:b], secondary[a:b], sample_rate)
        if estimated is None:
            rejected[sec_id] = "uncertain_local_delay"
            continue
        lag_core, slope, similarity = estimated
        # Evaluate delay relative to chunk index 0 so edge padding shares consistent slope.
        lag0 = lag_core - slope * a
        mid_lag = round(lag0 + slope * ((a + b) / 2.0))
        shared_start = max(a, -mid_lag)
        shared_end = min(b, len(secondary) - mid_lag)
        if shared_end <= shared_start:
            rejected[sec_id] = "no_shared_overlap"
            continue
        reference_level = float(np.linalg.norm(reference[shared_start:shared_end]))
        secondary_level = float(
            np.linalg.norm(secondary[shared_start + mid_lag : shared_end + mid_lag])
        )
        gain = float(np.clip(reference_level / max(secondary_level, 1e-8), 0.5, 2.0))

        sec_weight = np.zeros(len(reference), dtype=np.float64)
        aligned_sec = np.zeros(len(reference), dtype=np.float32)
        src_weight = max(float(sec_score), 1e-4)

        for ref_start, ref_end in ref_intervals:
            for src_start, src_end in recorded_intervals(secondary_coverage, fallback):
                base_left = max(0, round(ref_start * sample_rate) - clip_start)
                base_right = min(len(reference), round(ref_end * sample_rate) - clip_start)
                if base_right <= base_left:
                    continue
                idx = np.arange(base_left, base_right, dtype=np.float64)
                sec_pos = idx + lag0 + slope * idx
                src_min = max(0.0, float(round(src_start * sample_rate) - clip_start))
                src_max = min(
                    float(len(secondary) - 1),
                    float(round(src_end * sample_rate) - clip_start - 1),
                )
                valid_indices = np.flatnonzero((sec_pos >= src_min) & (sec_pos <= src_max))
                if not len(valid_indices):
                    continue
                left = base_left + int(valid_indices[0])
                right = base_left + int(valid_indices[-1]) + 1
                sub_pos = sec_pos[valid_indices[0] : valid_indices[-1] + 1]
                aligned_slice = _sample_shifted(secondary, sub_pos, slope, lag0)
                fade = min(round(0.005 * sample_rate), (right - left) // 2)
                w = np.full(right - left, src_weight, dtype=np.float64)
                if fade:
                    ramp = np.linspace(0.0, 1.0, fade, dtype=np.float64)
                    w[:fade] *= ramp
                    w[-fade:] *= ramp[::-1]
                sec_weight[left:right] = w
                aligned_sec[left:right] = aligned_slice

        if not float(np.sum(sec_weight)) > 0:
            rejected[sec_id] = "no_shared_coverage"
            continue
        numerator += sec_weight * gain * aligned_sec
        denominator += sec_weight
        weight_traces[sec_id] = sec_weight
        accepted[sec_id] = {
            "lag_samples": mid_lag,
            "slope_samples_per_sec": round(slope * sample_rate, 3),
            "similarity": similarity,
            "gain": gain,
        }

    if not accepted:
        details: dict[str, Any] = {"fallback_reason": "uncertain_local_delay"}
        if rejected:
            details["rejected_secondary_reasons"] = rejected
        return reference, details

    mixed = (numerator / np.maximum(denominator, 1e-8)).astype(np.float32)
    peak = float(np.max(np.abs(mixed), initial=0.0))
    output_gain = min(1.0, 0.999 / max(peak, 1e-8))
    contributors = {
        src_id: round(float(np.mean(trace / np.maximum(denominator, 1e-8))), 6)
        for src_id, trace in weight_traces.items()
    }
    first_id = next(iter(accepted))
    first = accepted[first_id]
    details = {
        "secondary_lag_samples": first["lag_samples"],
        "secondary_lags_samples": {sid: meta["lag_samples"] for sid, meta in accepted.items()},
        "alignment_correlation_min": min(meta["similarity"] for meta in accepted.values()),
        "secondary_gain": first["gain"],
        "output_gain": output_gain,
        "contributors": contributors,
    }
    if rejected:
        details["rejected_secondary_reasons"] = rejected
    return (mixed * output_gain).astype(np.float32, copy=False), details


def fuse_pair(
    reference: FloatAudio,
    secondary: FloatAudio,
    *,
    clip_start: int,
    core: tuple[int, int],
    sample_rate: int,
    reference_coverage: dict[str, Any],
    secondary_coverage: dict[str, Any],
    secondary_weight: float,
) -> tuple[FloatAudio, dict[str, Any]]:
    """Keep the reference clock and fall back where both channels cannot contribute."""
    ref_weight = max(1.0 - secondary_weight, 1e-4)
    return fuse_sources(
        [
            ("reference", reference, reference_coverage, ref_weight),
            ("secondary", secondary, secondary_coverage, max(secondary_weight, 1e-4)),
        ],
        clip_start=clip_start,
        core=core,
        sample_rate=sample_rate,
    )


def afftdn(waveform: FloatAudio, sample_rate: int) -> FloatAudio:
    """Filter one chunk and compensate afftdn's two-hop analysis delay."""
    # FFmpeg afftdn implements a three-hop window with sample_rate // 80 per hop.
    delay = 2 * (sample_rate // 80)
    padded = np.pad(waveform, (0, delay)).astype("<f4", copy=False)
    result = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-f",
            "f32le",
            "-ar",
            str(sample_rate),
            "-ac",
            "1",
            "-i",
            "pipe:0",
            "-af",
            "afftdn=nr=6:nf=-45:tn=1",
            "-f",
            "f32le",
            "pipe:1",
        ],
        input=padded.tobytes(),
        capture_output=True,
        check=True,
        timeout=10,
    )
    output = np.frombuffer(result.stdout, dtype="<f4")[delay:]
    if output.shape != waveform.shape or not np.isfinite(output).all():
        raise ValueError("afftdn output violates the ASR sample contract")
    return output.astype(np.float32, copy=False)
