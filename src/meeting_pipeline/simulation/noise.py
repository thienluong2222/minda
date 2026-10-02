"""Acoustic noise generator adhering strictly to VIVOS-only corpus rules.

Specification: Section 7.4 of docs/PLAN_VIVOS_SYNTHETIC_PIPELINE.md.
"""

from __future__ import annotations

import random
from typing import Any

import numpy as np
import soundfile as sf

from meeting_pipeline.domain.contracts import UtteranceRecord


def generate_white_noise(
    length_samples: int,
    rng: np.random.Generator,
) -> np.ndarray[Any, np.dtype[np.float32]]:
    """Generate normalized zero-mean white Gaussian noise."""
    if length_samples <= 0:
        return np.zeros(0, dtype=np.float32)
    noise = rng.normal(0.0, 1.0, size=length_samples).astype(np.float32)
    std = float(np.std(noise))
    if std > 1e-8:
        noise = noise / std
    return noise


def generate_pink_noise(
    length_samples: int,
    rng: np.random.Generator,
) -> np.ndarray[Any, np.dtype[np.float32]]:
    """Generate pink noise (1/f) via Voss-McCartney filtering of white noise."""
    if length_samples <= 0:
        return np.zeros(0, dtype=np.float32)
    white = rng.normal(0.0, 1.0, size=length_samples).astype(np.float32)
    # Simple IIR 1/f filter approximation
    # Pink noise filter coefficients (Paul Kellet's method)
    b = [0.049922035, -0.095993537, 0.050612699, -0.004408786]
    a = [1.0, -2.494956002, 2.017265875, -0.5221894]
    from scipy.signal import lfilter

    pink = lfilter(b, a, white).astype(np.float32)
    std = float(np.std(pink))
    if std > 1e-8:
        pink = pink / std
    return pink


def generate_brown_noise(
    length_samples: int,
    rng: np.random.Generator,
) -> np.ndarray[Any, np.dtype[np.float32]]:
    """Generate brownian/red noise (1/f^2) via cumulative integration."""
    if length_samples <= 0:
        return np.zeros(0, dtype=np.float32)
    white = rng.normal(0.0, 1.0, size=length_samples).astype(np.float32)
    brown = np.cumsum(white).astype(np.float32)
    brown -= np.mean(brown)
    std = float(np.std(brown))
    if std > 1e-8:
        brown = brown / std
    return brown


def generate_hum_noise(
    length_samples: int,
    sample_rate: int = 16000,
    base_freq: float = 50.0,
    harmonics: int = 3,
) -> np.ndarray[Any, np.dtype[np.float32]]:
    """Generate 50Hz electrical mains hum with harmonics."""
    if length_samples <= 0:
        return np.zeros(0, dtype=np.float32)
    t = np.arange(length_samples, dtype=np.float32) / sample_rate
    hum = np.zeros(length_samples, dtype=np.float32)
    for h in range(1, harmonics + 1):
        freq = base_freq * h
        amp = 1.0 / (h**1.2)
        phase = float(np.random.uniform(0, 2 * np.pi))
        hum += (amp * np.sin(2 * np.pi * freq * t + phase)).astype(np.float32)

    std = float(np.std(hum))
    if std > 1e-8:
        hum = hum / std
    return hum


def generate_vivos_room_tone(
    vivos_records: list[UtteranceRecord],
    length_samples: int,
    sample_rate: int = 16000,
    py_rng: random.Random | None = None,
) -> np.ndarray[Any, np.dtype[np.float32]]:
    """Extract ambient room tone from silent leading/trailing frames of VIVOS audio files."""
    rng = py_rng or random.Random(42)
    tone_slices: list[np.ndarray[Any, np.dtype[np.float32]]] = []

    sampled_records = rng.sample(vivos_records, min(len(vivos_records), 30))
    for r in sampled_records:
        try:
            data, sr = sf.read(r.audio_path, dtype="float32")
            if sr != sample_rate:
                continue
            # Extract first 0.15s (silence before speech onset)
            slice_len = int(0.15 * sample_rate)
            if len(data) > slice_len:
                head = data[:slice_len]
                # Verify that it is indeed low energy silence
                if np.max(np.abs(head)) < 0.05:
                    tone_slices.append(head)
        except Exception:
            continue

    if not tone_slices:
        np_rng = np.random.default_rng(42)
        return generate_pink_noise(length_samples, np_rng) * 0.05

    # Concatenate and loop to fill length_samples
    full_pool = np.concatenate(tone_slices)
    repeats = int(np.ceil(length_samples / len(full_pool)))
    tiled = np.tile(full_pool, repeats)[:length_samples]
    tiled -= np.mean(tiled)
    std = float(np.std(tiled))
    if std > 1e-8:
        tiled = tiled / std
    return tiled


def generate_vivos_babble_noise(
    vivos_records_in_split: list[UtteranceRecord],
    excluded_utterance_ids: set[str],
    length_samples: int,
    num_talkers: int = 4,
    sample_rate: int = 16000,
    py_rng: random.Random | None = None,
) -> np.ndarray[Any, np.dtype[np.float32]]:
    """Generate multi-speaker babble noise solely using other VIVOS utterances in the same split."""
    rng = py_rng or random.Random(42)
    eligible_records = [
        r for r in vivos_records_in_split if r.utterance_id not in excluded_utterance_ids
    ]
    if not eligible_records:
        np_rng = np.random.default_rng(42)
        return generate_pink_noise(length_samples, np_rng)

    babble = np.zeros(length_samples, dtype=np.float32)
    for _ in range(num_talkers):
        talker_track = np.zeros(length_samples, dtype=np.float32)
        curr_pos = 0
        while curr_pos < length_samples:
            r = rng.choice(eligible_records)
            try:
                data, _ = sf.read(r.audio_path, dtype="float32")
                if len(data) == 0:
                    continue
                end_pos = min(length_samples, curr_pos + len(data))
                talker_track[curr_pos:end_pos] += data[: end_pos - curr_pos]
                curr_pos = end_pos + int(rng.uniform(0.1, 0.4) * sample_rate)
            except Exception:
                curr_pos += int(0.5 * sample_rate)
        babble += talker_track

    babble -= np.mean(babble)
    std = float(np.std(babble))
    if std > 1e-8:
        babble = babble / std
    return babble


def scale_noise_to_snr(
    speech: np.ndarray[Any, np.dtype[np.float32]],
    noise: np.ndarray[Any, np.dtype[np.float32]],
    target_snr_db: float,
) -> np.ndarray[Any, np.dtype[np.float32]]:
    """Scale noise so speech has target_snr_db relative to speech-active samples.

    SNR = 10 * log10(P_speech / P_noise)
    P_noise = P_speech / (10^(SNR/10))
    """
    # Find active speech samples (samples with amplitude > 0.01)
    active_mask = np.abs(speech) > 0.005
    if not np.any(active_mask):
        speech_power = float(np.mean(speech**2)) if len(speech) > 0 else 1.0
    else:
        speech_power = float(np.mean(speech[active_mask] ** 2))

    if speech_power < 1e-9:
        speech_power = 1e-4

    target_noise_power = speech_power / (10.0 ** (target_snr_db / 10.0))
    current_noise_power = float(np.mean(noise**2)) if len(noise) > 0 else 1.0
    if current_noise_power < 1e-9:
        current_noise_power = 1.0

    scaling = float(np.sqrt(target_noise_power / current_noise_power))
    return (noise * scaling).astype(np.float32)
