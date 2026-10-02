"""Audio utilities for loading, resampling, and validating mono 16kHz audio."""

from __future__ import annotations

import hashlib
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf


def load_audio_mono_16k(
    path: Path | str,
    target_sr: int = 16000,
    min_duration_sec: float = 0.5,
) -> np.ndarray:
    """Load an audio file as mono float32 16kHz numpy array."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Audio file not found: {path}")

    waveform, sr = sf.read(path, dtype="float32")
    if waveform.ndim > 1:
        waveform = waveform.mean(axis=1)

    if sr != target_sr:
        waveform = librosa.resample(waveform, orig_sr=sr, target_sr=target_sr)

    waveform = waveform.astype(np.float32)

    # Pad if shorter than min_duration_sec
    min_samples = int(min_duration_sec * target_sr)
    if waveform.size < min_samples:
        pad_width = min_samples - waveform.size
        waveform = np.pad(waveform, (0, pad_width), mode="constant")

    validate_waveform(waveform)
    return np.asarray(waveform, dtype=np.float32)


def normalize_waveform(
    waveform: np.ndarray,
    target_sr: int = 16000,
    source_sr: int = 16000,
    min_duration_sec: float = 0.5,
) -> np.ndarray:
    """Ensure in-memory waveform is 1D mono float32 16kHz and valid."""
    if waveform.ndim > 1:
        waveform = waveform.mean(axis=1)

    if source_sr != target_sr:
        waveform = librosa.resample(
            waveform.astype(np.float32), orig_sr=source_sr, target_sr=target_sr
        )

    waveform = waveform.astype(np.float32)

    min_samples = int(min_duration_sec * target_sr)
    if waveform.size < min_samples:
        pad_width = min_samples - waveform.size
        waveform = np.pad(waveform, (0, pad_width), mode="constant")

    validate_waveform(waveform)
    return np.asarray(waveform, dtype=np.float32)


def validate_waveform(waveform: np.ndarray) -> None:
    """Check that waveform is a 1-D finite float32 numpy array."""
    if waveform.ndim != 1:
        raise ValueError(f"Expected 1-D waveform, got shape {waveform.shape}")
    if not np.all(np.isfinite(waveform)):
        raise ValueError("Waveform contains NaN or Inf values")
    if waveform.size == 0:
        raise ValueError("Waveform is empty")


def compute_audio_sha256(waveform: np.ndarray) -> str:
    """Compute deterministic SHA-256 hash of a float32 waveform."""
    validate_waveform(waveform)
    # Ensure C-contiguous bytes
    contiguous = np.ascontiguousarray(waveform, dtype=np.float32)
    return hashlib.sha256(contiguous.tobytes()).hexdigest()
