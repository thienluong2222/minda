"""Observed source quality features and scoring functions.

Specification: Section 12 of docs/PLAN_VIVOS_SYNTHETIC_PIPELINE.md.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def extract_acoustic_features(
    waveform: np.ndarray[Any, np.dtype[np.float32]],
    sample_rate: int = 16000,
    vad_confidence: float = 0.8,
) -> dict[str, float]:
    """Compute observed acoustic quality features without oracle parameters."""
    if len(waveform) == 0:
        return {
            "rms": 0.0,
            "snr_est": 0.0,
            "clipping_ratio": 0.0,
            "dropout_ratio": 1.0,
            "vad_confidence": 0.0,
            "spectral_flatness": 0.0,
            "zero_crossing_rate": 0.0,
        }

    # 1. RMS
    rms = float(np.sqrt(np.mean(waveform**2)))

    # 2. Clipping ratio (samples >= 0.98 of max range)
    clipping_ratio = float(np.mean(np.abs(waveform) >= 0.98))

    # 3. Dropout / near-zero ratio during speech
    dropout_ratio = float(np.mean(np.abs(waveform) < 1e-4))

    # 4. Estimated local SNR (ratio of active frames power to quiet frames power)
    frame_len = int(0.02 * sample_rate)  # 20ms frames
    if len(waveform) >= frame_len:
        usable = len(waveform) - (len(waveform) % frame_len)
        frames = waveform[:usable].reshape(-1, frame_len)
        frame_powers = np.mean(frames**2, axis=1)
        # Median power as noise floor estimate
        noise_floor = float(np.percentile(frame_powers, 20))
        signal_floor = float(np.percentile(frame_powers, 80))
        if noise_floor > 1e-9:
            snr_lin = signal_floor / noise_floor
            snr_db = float(10.0 * np.log10(max(1.0, snr_lin)))
        else:
            snr_db = 30.0
    else:
        snr_db = 20.0

    # 5. Zero-crossing rate
    zcr = float(np.mean(np.abs(np.diff(np.sign(waveform)))) / 2.0)

    # 6. Spectral flatness proxy
    fft_mag = np.abs(np.fft.rfft(waveform)) + 1e-8
    geom_mean = float(np.exp(np.mean(np.log(fft_mag))))
    arith_mean = float(np.mean(fft_mag))
    flatness = float(geom_mean / max(arith_mean, 1e-8))

    return {
        "rms": round(rms, 4),
        "snr_est": round(snr_db, 2),
        "clipping_ratio": round(clipping_ratio, 4),
        "dropout_ratio": round(dropout_ratio, 4),
        "vad_confidence": round(vad_confidence, 4),
        "spectral_flatness": round(flatness, 4),
        "zero_crossing_rate": round(zcr, 4),
    }


def compute_audio_quality_score(
    features: dict[str, float],
    weights: dict[str, float] | None = None,
) -> float:
    """Calculate normalized audio_quality_score in [0.0, 1.0].

    Features with positive sign: snr_est, vad_confidence.
    Features with negative sign (penalties): clipping_ratio, dropout_ratio.
    """
    w = weights or {
        "snr_est": 0.35,
        "vad_confidence": 0.35,
        "clipping_penalty": 0.15,
        "dropout_penalty": 0.15,
    }

    # Map snr_est (0 to 30 dB) -> [0, 1]
    norm_snr = max(0.0, min(1.0, features.get("snr_est", 15.0) / 30.0))
    norm_vad = max(0.0, min(1.0, features.get("vad_confidence", 0.5)))

    clip_pen = min(1.0, features.get("clipping_ratio", 0.0) * 20.0)  # 5% clipping -> 1.0 penalty
    drop_pen = min(1.0, features.get("dropout_ratio", 0.0) * 10.0)

    score = (
        w.get("snr_est", 0.35) * norm_snr
        + w.get("vad_confidence", 0.35) * norm_vad
        + w.get("clipping_penalty", 0.15) * (1.0 - clip_pen)
        + w.get("dropout_penalty", 0.15) * (1.0 - drop_pen)
    )

    return float(max(0.0, min(1.0, score)))


def compute_transcript_quality_score(
    audio_quality_score: float,
    asr_confidence: float,
    word_agreement: float = 1.0,
    weights: dict[str, float] | None = None,
) -> float:
    """Calculate normalized transcript_quality_score in [0.0, 1.0]."""
    w = weights or {
        "audio_quality": 0.40,
        "asr_confidence": 0.40,
        "word_agreement": 0.20,
    }

    score = (
        w.get("audio_quality", 0.40) * audio_quality_score
        + w.get("asr_confidence", 0.40) * asr_confidence
        + w.get("word_agreement", 0.20) * word_agreement
    )

    return float(max(0.0, min(1.0, score)))
