"""Multi-channel acoustic renderer for simulated meeting recipes.

Specification: Section 7.2 of docs/PLAN_VIVOS_SYNTHETIC_PIPELINE.md.
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Any

import numpy as np
import scipy.signal
import soundfile as sf

from meeting_pipeline.domain.contracts import MeetingRecipe, MeetingSegment, UtteranceRecord
from meeting_pipeline.simulation.device import (
    apply_clipping,
    apply_clock_drift,
    apply_dropout,
    apply_start_offset,
)
from meeting_pipeline.simulation.noise import (
    generate_brown_noise,
    generate_hum_noise,
    generate_pink_noise,
    generate_vivos_babble_noise,
    generate_vivos_room_tone,
    generate_white_noise,
    scale_noise_to_snr,
)
from meeting_pipeline.simulation.room import compute_room_rirs

logger = logging.getLogger(__name__)


def render_meeting_audio(
    recipe: MeetingRecipe,
    manifest_records: list[UtteranceRecord],
    output_dir: Path | str,
    sample_rate: int = 16000,
    save_debug_clean: bool = True,
) -> dict[str, Path]:
    """Render simulated multi-device audio from a canonical meeting recipe.

    Formula:
        x_d(t) = sum_s [h_(s,d)(t) * y_s(t)] + n_d(t)
    followed by device gain, start offset, clock drift, clipping and dropout.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    utt_lookup = {r.utterance_id: r for r in manifest_records}
    split_records = [r for r in manifest_records if r.split == recipe.split]

    total_samples = round(recipe.canonical_duration_sec * sample_rate)
    if total_samples <= 0:
        raise ValueError(f"Invalid duration: {recipe.canonical_duration_sec}s")

    # 1. Build clean speaker stems on the canonical timeline
    speaker_stems: dict[str, np.ndarray[Any, np.dtype[np.float32]]] = {
        spk: np.zeros(total_samples, dtype=np.float32) for spk in recipe.speakers
    }

    clean_mix = np.zeros(total_samples, dtype=np.float32)

    for turn in recipe.turns:
        utt_record = utt_lookup.get(turn.utterance_id)
        if utt_record is None:
            raise KeyError(f"Utterance {turn.utterance_id} not in manifest")

        audio_data, sr = sf.read(utt_record.audio_path, dtype="float32")
        if sr != sample_rate:
            raise ValueError(f"Unexpected sample rate {sr} in {utt_record.audio_path}")

        start_samp = round(turn.start_sec * sample_rate)
        end_samp = start_samp + len(audio_data)

        # Truncate if exceeding canonical length
        if end_samp > total_samples:
            audio_data = audio_data[: total_samples - start_samp]
            end_samp = total_samples

        if len(audio_data) > 0 and start_samp < total_samples:
            speaker_stems[turn.speaker_id][start_samp:end_samp] += audio_data
            clean_mix[start_samp:end_samp] += audio_data

    # 2. Compute 3D RIRs for all (speaker, device) pairs
    device_positions = {dev_id: dev.position for dev_id, dev in recipe.devices.items()}
    rirs = compute_room_rirs(
        dimensions=recipe.room.dimensions,
        rt60=recipe.room.rt60,
        speaker_positions=recipe.speaker_positions,
        device_positions=device_positions,
        sample_rate=sample_rate,
    )

    rendered_files: dict[str, Path] = {}

    # 3. Render each device
    dev_rng = np.random.default_rng(recipe.seed)
    py_rng = random.Random(recipe.seed)

    excluded_utts = {turn.utterance_id for turn in recipe.turns}

    for dev_id, dev_cfg in sorted(recipe.devices.items()):
        # Convolve each speaker stem with respective RIR
        device_speech = np.zeros(total_samples, dtype=np.float32)
        for spk_id in recipe.speakers:
            rir = rirs[spk_id][dev_id]
            stem = speaker_stems[spk_id]
            # Fast FFT convolution
            convolved = scipy.signal.fftconvolve(stem, rir, mode="full").astype(np.float32)
            # Add to device speech (cut to canonical duration)
            valid_len = min(total_samples, len(convolved))
            device_speech[:valid_len] += convolved[:valid_len]

        # Generate device noise
        noise_t = dev_cfg.noise_type
        if noise_t == "white":
            raw_noise = generate_white_noise(total_samples, dev_rng)
        elif noise_t == "pink":
            raw_noise = generate_pink_noise(total_samples, dev_rng)
        elif noise_t == "brown":
            raw_noise = generate_brown_noise(total_samples, dev_rng)
        elif noise_t == "hum_50hz":
            raw_noise = generate_hum_noise(total_samples, sample_rate=sample_rate)
        elif noise_t == "room_tone":
            raw_noise = generate_vivos_room_tone(
                split_records, total_samples, sample_rate, py_rng=py_rng
            )
        elif noise_t == "babble":
            raw_noise = generate_vivos_babble_noise(
                split_records,
                excluded_utts,
                total_samples,
                num_talkers=3,
                sample_rate=sample_rate,
                py_rng=py_rng,
            )
        else:
            raw_noise = generate_pink_noise(total_samples, dev_rng)

        # Scale noise to target SNR
        scaled_noise = scale_noise_to_snr(device_speech, raw_noise, dev_cfg.snr_db)
        dev_audio = device_speech + scaled_noise

        # Apply device gain
        gain_linear = 10.0 ** (dev_cfg.gain_db / 20.0)
        dev_audio = dev_audio * gain_linear

        # Apply start offset and clock drift
        dev_audio = apply_start_offset(dev_audio, dev_cfg.offset_sec, sample_rate)
        dev_audio = apply_clock_drift(dev_audio, dev_cfg.drift_ppm)

        # Apply clipping and dropout if configured
        if dev_cfg.clipping_ratio > 0.0:
            dev_audio = apply_clipping(dev_audio, dev_cfg.clipping_ratio)
        if dev_cfg.dropout_count > 0:
            dev_audio = apply_dropout(dev_audio, dev_cfg.dropout_count, sample_rate, py_rng)

        # Write WAV file (16-bit PCM mono 16kHz)
        dev_path = out_dir / f"{dev_id}.wav"
        # Normalize to [-0.98, 0.98] to prevent unintended clipping during write
        max_abs = float(np.max(np.abs(dev_audio))) if len(dev_audio) > 0 else 0.0
        if max_abs > 0.98:
            dev_audio = dev_audio * (0.95 / max_abs)

        sf.write(str(dev_path), dev_audio, sample_rate, subtype="PCM_16")
        rendered_files[dev_id] = dev_path

    # Save clean reference audio if requested (for evaluation/debugging)
    if save_debug_clean:
        ref_path = out_dir / "clean_reference.wav"
        ref_max = float(np.max(np.abs(clean_mix))) if len(clean_mix) > 0 else 0.0
        if ref_max > 0.98:
            clean_mix = clean_mix * (0.95 / ref_max)
        sf.write(str(ref_path), clean_mix, sample_rate, subtype="PCM_16")
        rendered_files["clean_reference"] = ref_path

    # Save recipe JSON alongside audio
    recipe_path = out_dir / "recipe.json"
    with open(recipe_path, "w", encoding="utf-8") as f:
        f.write(recipe.model_dump_json(indent=2))

    # Save reference evaluation segments
    ref_segments = [
        MeetingSegment(
            schema_version="1.0",
            meeting_id=recipe.meeting_id,
            segment_id=f"seg_{i:04d}",
            start_sec=turn.start_sec,
            end_sec=turn.end_sec,
            overlap=False,
            reference_speaker_id=turn.speaker_id,
            reference_text=turn.text_normalized,
        )
        for i, turn in enumerate(recipe.turns)
    ]
    segs_path = out_dir / "reference_segments.json"
    with open(segs_path, "w", encoding="utf-8") as f:
        json.dump([s.model_dump() for s in ref_segments], f, ensure_ascii=False, indent=2)

    return rendered_files
