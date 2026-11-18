"""Conservative two-microphone delay-and-sum for a single-speaker ASR chunk."""

from __future__ import annotations

import subprocess
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
) -> tuple[int, float] | None:
    """Positive lag means the secondary signal arrives later than the reference."""
    limit = round(0.04 * sample_rate)
    n_fft = next_fast_len(2 * len(reference) - 1)
    window = np.hanning(len(reference))
    a = (reference - np.mean(reference)) * window
    b = (secondary - np.mean(secondary)) * window
    cross = rfft(b, n_fft) * rfft(a, n_fft).conj()
    frequencies = rfftfreq(n_fft, 1 / sample_rate)
    band = (frequencies >= 150) & (frequencies <= min(6500, sample_rate / 2))
    phat = np.where(band, cross / np.maximum(np.abs(cross), 1e-12), 0)
    correlation = irfft(phat, n_fft)
    search = np.r_[correlation[-limit:], correlation[: limit + 1]]
    index = int(np.argmax(search))
    lag = index - limit
    if abs(lag) == limit:
        return None
    other = np.abs(np.r_[search[: max(0, index - 2)], search[index + 3 :]])
    if search[index] <= 1.25 * float(np.max(other, initial=1e-12)):
        return None

    left, right = max(0, -lag), min(len(a), len(a) - lag)
    first, second = a[left:right], b[left + lag : right + lag]
    norm = float(np.linalg.norm(first) * np.linalg.norm(second))
    similarity = float(np.dot(first, second) / norm) if norm else 0.0
    return (lag, similarity) if similarity >= 0.55 else None


def _stable_lag(
    reference: FloatAudio, secondary: FloatAudio, sample_rate: int
) -> tuple[int, float] | None:
    if len(reference) < round(0.35 * sample_rate):
        return None
    frame = min(len(reference), sample_rate)
    starts = range(0, len(reference) - frame + 1, max(1, frame // 2))
    starts = sorted({*starts, len(reference) - frame})
    peak_rms = max(float(np.linalg.norm(reference[start : start + frame])) for start in starts)
    if peak_rms <= 1e-6:
        return None
    estimates = []
    for start in starts:
        a, b = reference[start : start + frame], secondary[start : start + frame]
        if np.linalg.norm(a) < 0.25 * peak_rms:
            continue
        estimate = _window_lag(a, b, sample_rate)
        if estimate is None:
            return None
        estimates.append(estimate)
    lags = [lag for lag, _ in estimates]
    if not lags or max(lags) - min(lags) > 1:
        return None
    return round(float(np.median(lags))), min(score for _, score in estimates)


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
    a, b = core[0] - clip_start, core[1] - clip_start
    if a < 0 or b > len(reference) or len(reference) != len(secondary):
        return reference, {"fallback_reason": "incomplete_chunk"}
    estimated = _stable_lag(reference[a:b], secondary[a:b], sample_rate)
    if estimated is None:
        return reference, {"fallback_reason": "uncertain_local_delay"}
    lag, similarity = estimated
    # Keep the reference alone at any edge exposed by the shift.
    shared_start, shared_end = max(a, -lag), min(b, len(secondary) - lag)
    reference_level = float(np.linalg.norm(reference[shared_start:shared_end]))
    secondary_level = float(np.linalg.norm(secondary[shared_start + lag : shared_end + lag]))
    gain = float(np.clip(reference_level / max(secondary_level, 1e-8), 0.5, 2.0))
    fallback = (clip_start / sample_rate, (clip_start + len(reference)) / sample_rate)
    mixed = reference.copy()
    for ref_start, ref_end in recorded_intervals(reference_coverage, fallback):
        for src_start, src_end in recorded_intervals(secondary_coverage, fallback):
            left = max(
                0,
                -lag,
                round(ref_start * sample_rate) - clip_start,
                round(src_start * sample_rate) - clip_start - lag,
            )
            right = min(
                len(reference),
                len(secondary) - lag,
                round(ref_end * sample_rate) - clip_start,
                round(src_end * sample_rate) - clip_start - lag,
            )
            if right <= left:
                continue
            # Fade the secondary at the edges rather than wrapping samples or mixing padding.
            weight = np.full(right - left, secondary_weight, dtype=np.float32)
            fade = min(round(0.005 * sample_rate), len(weight) // 2)
            if fade:
                ramp = np.linspace(0, 1, fade, dtype=np.float32)
                weight[:fade] *= ramp
                weight[-fade:] *= ramp[::-1]
            mixed[left:right] = (1 - weight) * reference[left:right] + weight * gain * secondary[
                left + lag : right + lag
            ]
    # Use uniform peak attenuation so the sum does not clip.
    peak = float(np.max(np.abs(mixed), initial=0.0))
    output_gain = min(1.0, 0.999 / max(peak, 1e-8))
    return mixed * output_gain, {
        "secondary_lag_samples": lag,
        "alignment_correlation_min": similarity,
        "secondary_gain": gain,
        "output_gain": output_gain,
    }


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
