"""Device hardware modeling: gain, start offset, clock drift, clipping and dropout.

Specification: Section 7.5 of docs/PLAN_VIVOS_SYNTHETIC_PIPELINE.md.
"""

from __future__ import annotations

import random
from typing import Any, cast

import numpy as np


def apply_start_offset(
    signal: np.ndarray[Any, np.dtype[np.float32]],
    offset_sec: float,
    sample_rate: int = 16000,
) -> np.ndarray[Any, np.dtype[np.float32]]:
    """Shift recording timeline by offset_sec.

    - Positive offset: device started recording LATER (prepend zeros).
    - Negative offset: device started recording EARLIER (trim front).
    """
    shift_samples = round(offset_sec * sample_rate)
    if shift_samples == 0:
        return signal.copy()

    if shift_samples > 0:
        # Pad leading silence
        pad = np.zeros(shift_samples, dtype=np.float32)
        return np.concatenate([pad, signal])
    else:
        # Trim leading samples
        trim_samples = abs(shift_samples)
        if trim_samples >= len(signal):
            return np.zeros(0, dtype=np.float32)
        return signal[trim_samples:].copy()


def apply_clock_drift(
    signal: np.ndarray[Any, np.dtype[np.float32]],
    drift_ppm: float,
) -> np.ndarray[Any, np.dtype[np.float32]]:
    """Simulate crystal oscillator clock drift specified in parts per million (ppm).

    Ratio = 1.0 + drift_ppm * 1e-6.
    """
    if abs(drift_ppm) < 1e-3 or len(signal) < 2:
        return signal.copy()

    ratio = 1.0 + (drift_ppm * 1e-6)
    orig_len = len(signal)
    new_len = round(orig_len / ratio)

    if new_len < 2:
        return signal.copy()

    x_orig = np.linspace(0.0, 1.0, orig_len, endpoint=True)
    x_new = np.linspace(0.0, 1.0, new_len, endpoint=True)

    resampled = np.interp(x_new, x_orig, signal).astype(np.float32)
    return cast(np.ndarray[Any, np.dtype[np.float32]], resampled)


def apply_clipping(
    signal: np.ndarray[Any, np.dtype[np.float32]],
    clipping_ratio: float,
) -> np.ndarray[Any, np.dtype[np.float32]]:
    """Simulate microphone pre-amp clipping on top percentile of amplitude."""
    if clipping_ratio <= 0.0 or len(signal) == 0:
        return signal.copy()

    # Find the threshold percentile above which samples are clipped
    percentile = max(50.0, 100.0 * (1.0 - clipping_ratio))
    clip_level = float(np.percentile(np.abs(signal), percentile))

    if clip_level <= 1e-6:
        return signal.copy()

    clipped = np.clip(signal, -clip_level, clip_level).astype(np.float32)
    return cast(np.ndarray[Any, np.dtype[np.float32]], clipped)


def apply_dropout(
    signal: np.ndarray[Any, np.dtype[np.float32]],
    dropout_count: int,
    sample_rate: int = 16000,
    py_rng: random.Random | None = None,
) -> np.ndarray[Any, np.dtype[np.float32]]:
    """Simulate transmission packet loss or buffer dropouts."""
    if dropout_count <= 0 or len(signal) == 0:
        return signal.copy()

    rng = py_rng or random.Random(42)
    out = signal.copy()

    for _ in range(dropout_count):
        drop_dur = rng.uniform(0.05, 0.20)  # 50ms to 200ms
        drop_samples = int(drop_dur * sample_rate)
        if len(out) > drop_samples:
            start_idx = rng.randint(0, len(out) - drop_samples)
            out[start_idx : start_idx + drop_samples] = 0.0

    return out
