"""Unit and integration tests for multi-device simulation (Milestone 3)."""

from pathlib import Path

import numpy as np
import soundfile as sf

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
    generate_white_noise,
    scale_noise_to_snr,
)
from meeting_pipeline.simulation.room import compute_direct_path_energy, compute_room_rirs


def test_room_rir_physical_direct_path_energy() -> None:
    """Verify that a device closer to speaker A has higher direct energy than a distant device."""
    dims = [6.0, 5.0, 3.0]
    rt60 = 0.3
    speaker_positions = {
        "spk_A": [2.0, 2.0, 1.2],
        "spk_B": [4.5, 3.5, 1.2],
    }
    device_positions = {
        "dev_near_A": [2.2, 2.0, 0.8],  # ~0.45m from spk_A
        "dev_far_A": [5.0, 4.0, 0.8],  # ~3.6m from spk_A
    }

    rirs = compute_room_rirs(
        dimensions=dims,
        rt60=rt60,
        speaker_positions=speaker_positions,
        device_positions=device_positions,
        sample_rate=16000,
    )

    rir_near_A = rirs["spk_A"]["dev_near_A"]
    rir_far_A = rirs["spk_A"]["dev_far_A"]

    energy_near = compute_direct_path_energy(rir_near_A)
    energy_far = compute_direct_path_energy(rir_far_A)

    msg = f"Near energy ({energy_near}) should be > far energy ({energy_far})"
    assert energy_near > energy_far * 2.0, msg


def test_device_effects() -> None:
    # 1. Start offset
    sig = np.ones(16000, dtype=np.float32)
    delayed = apply_start_offset(sig, 0.1, sample_rate=16000)
    assert len(delayed) == 16000 + 1600
    assert np.all(delayed[:1600] == 0.0)
    assert np.all(delayed[1600:] == 1.0)

    trimmed = apply_start_offset(sig, -0.1, sample_rate=16000)
    assert len(trimmed) == 16000 - 1600

    # 2. Clock drift
    drifted = apply_clock_drift(sig, 1000.0)  # 1000 ppm drift
    expected_len = round(16000 / (1.0 + 1000e-6))
    assert abs(len(drifted) - expected_len) <= 1

    # 3. Clipping
    wave = np.linspace(-2.0, 2.0, 100, dtype=np.float32)
    clipped = apply_clipping(wave, clipping_ratio=0.1)
    assert np.max(np.abs(clipped)) < 2.0

    # 4. Dropout
    signal_ones = np.ones(16000, dtype=np.float32)
    dropped = apply_dropout(signal_ones, dropout_count=2, sample_rate=16000)
    assert np.sum(dropped == 0.0) > 0


def test_noise_generation_properties() -> None:
    rng = np.random.default_rng(42)
    N = 8000
    white = generate_white_noise(N, rng)
    pink = generate_pink_noise(N, rng)
    brown = generate_brown_noise(N, rng)
    hum = generate_hum_noise(N, sample_rate=16000, base_freq=50.0)

    for noise in [white, pink, brown, hum]:
        assert len(noise) == N
        assert not np.any(np.isnan(noise))
        assert not np.any(np.isinf(noise))
        assert abs(np.std(noise) - 1.0) < 0.2

    # SNR scaling
    speech = np.ones(N, dtype=np.float32)
    scaled_noise = scale_noise_to_snr(speech, white, target_snr_db=20.0)
    p_speech = np.mean(speech**2)
    p_noise = np.mean(scaled_noise**2)
    measured_snr = 10.0 * np.log10(p_speech / p_noise)
    assert abs(measured_snr - 20.0) < 0.5


def test_rendered_smoke_meeting_audio_files() -> None:
    meeting_dir = Path("data/generated/smoke/meeting_development_001")
    assert meeting_dir.exists(), "Rendered meeting dir must exist"

    dev1_wav = meeting_dir / "device_01.wav"
    assert dev1_wav.exists()

    info = sf.info(str(dev1_wav))
    assert info.samplerate == 16000
    assert info.channels == 1
    assert info.duration > 100.0  # Smoke meeting is ~140s

    recipe_file = meeting_dir / "recipe.json"
    assert recipe_file.exists()

    segs_file = meeting_dir / "reference_segments.json"
    assert segs_file.exists()
