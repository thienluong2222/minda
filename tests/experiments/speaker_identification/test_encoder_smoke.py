"""Model smoke tests verifying offline encoding of real VIVOS audio for all required encoders."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from experiments.speaker_identification.audio import load_audio_mono_16k
from experiments.speaker_identification.encoders.mfcc import MFCCEncoder
from experiments.speaker_identification.encoders.pyannote_wespeaker import PyannoteWeSpeakerEncoder
from experiments.speaker_identification.encoders.speechbrain_ecapa import SpeechBrainECAPAEncoder
from experiments.speaker_identification.encoders.speechbrain_xvector import (
    SpeechBrainXVectorEncoder,
)
from experiments.speaker_identification.encoders.transformers_wavlm import TransformersWavLMEncoder


@pytest.mark.model_smoke
def test_all_encoders_offline_smoke() -> None:
    vivos_dir = Path("data/external/vivos/extracted/vivos/test/waves")
    if not vivos_dir.is_dir():
        pytest.skip("VIVOS test dataset not available")

    # Pick 2 audio files from same speaker (spk1) and 1 from different speaker (spk2)
    spk_dirs = sorted([p for p in vivos_dir.iterdir() if p.is_dir()])
    if len(spk_dirs) < 2:
        pytest.skip("Not enough speakers in VIVOS test")

    spk1_files = sorted(spk_dirs[0].glob("*.wav"))
    spk2_files = sorted(spk_dirs[1].glob("*.wav"))
    if len(spk1_files) < 2 or len(spk2_files) < 1:
        pytest.skip("Not enough audio files per speaker in VIVOS test")

    wave_a1 = load_audio_mono_16k(spk1_files[0])
    wave_a2 = load_audio_mono_16k(spk1_files[1])
    wave_b1 = load_audio_mono_16k(spk2_files[0])

    encoders = [
        MFCCEncoder(),
        SpeechBrainECAPAEncoder(),
        SpeechBrainXVectorEncoder(),
        PyannoteWeSpeakerEncoder(),
        TransformersWavLMEncoder(),
    ]

    for enc in encoders:
        emb_a1 = enc.encode(wave_a1)
        emb_a2 = enc.encode(wave_a2)
        emb_b1 = enc.encode(wave_b1)

        assert emb_a1.ndim == 1
        assert emb_a1.size == enc.embedding_dimension
        assert np.all(np.isfinite(emb_a1))
        assert pytest.approx(float(np.linalg.norm(emb_a1)), rel=1e-4) == 1.0

        # Diagnostics: same speaker cosine should typically be higher than different speaker
        cos_same = float(np.dot(emb_a1, emb_a2))
        cos_diff = float(np.dot(emb_a1, emb_b1))
        print(f"[{enc.encoder_id} - {enc.model_id}] same={cos_same:.4f}, diff={cos_diff:.4f}")
