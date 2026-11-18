"""Regression checks for migration between incompatible speaker embedding spaces."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from meeting_pipeline.application.speakers import SpeakerRegistry
from meeting_pipeline.config import load_config
from meeting_pipeline.speaker.encoder import (
    DEFAULT_SPEAKER_MODEL_ID,
    DEFAULT_SPEAKER_MODEL_REVISION,
)


class TargetEncoder:
    model_id = DEFAULT_SPEAKER_MODEL_ID
    revision = DEFAULT_SPEAKER_MODEL_REVISION
    embedding_dimension = 256

    def __init__(self):
        self.calls = 0

    def encode(self, wave):
        self.calls += 1
        vector = np.zeros(self.embedding_dimension, dtype=np.float32)
        vector[0] = 1.0
        return vector


def make_profile(
    tmp_path, *, dimension=192, model_id="old-speaker-model", revision="old-revision", audio=True
):
    config = load_config(Path("configs/default.yaml"))
    config.paths.data_dir = tmp_path
    registry = SpeakerRegistry(config)
    registry._encoder = TargetEncoder()
    folder = registry.root / "person"
    folder.mkdir(parents=True)
    metadata = {
        "speaker_id": "person",
        "display_name": "Test speaker",
        "model_id": model_id,
        "model_revision": revision,
        "embedding_dimension": dimension,
    }
    metadata_path = folder / "profile.json"
    embedding_path = folder / "embedding.npy"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    vector = np.zeros(dimension, dtype=np.float32)
    vector[-1] = 1.0
    np.save(embedding_path, vector)
    if audio:
        decoded = folder / "decoded"
        decoded.mkdir()
        speech = (0.1 * np.sin(2 * np.pi * 220 * np.arange(16000) / 16000)).astype(np.float32)
        sf.write(decoded / "sample-1.wav", np.pad(speech, (8000, 8000)), 16000)
    return registry, folder


def test_ecapa_profile_is_reencoded_with_metadata_backup_and_idempotence(tmp_path):
    registry, folder = make_profile(tmp_path)
    original_metadata = (folder / "profile.json").read_bytes()
    original_embedding = (folder / "embedding.npy").read_bytes()

    profiles = registry.load(["person"])
    assert profiles[0].speaker_id == "person"
    assert profiles[0].display_name == "Test speaker"
    assert profiles[0].embedding.shape == (256,)
    assert np.isclose(np.linalg.norm(profiles[0].embedding), 1.0)
    metadata = json.loads((folder / "profile.json").read_text())
    assert (metadata["model_id"], metadata["model_revision"], metadata["embedding_dimension"]) == (
        DEFAULT_SPEAKER_MODEL_ID,
        DEFAULT_SPEAKER_MODEL_REVISION,
        256,
    )
    backups = list((folder / "encoder_backups").iterdir())
    assert len(backups) == 1
    assert (backups[0] / "profile.json").read_bytes() == original_metadata
    assert (backups[0] / "embedding.npy").read_bytes() == original_embedding

    registry.load(["person"])
    assert registry._encoder.calls == 1
    assert len(list((folder / "encoder_backups").iterdir())) == 1


@pytest.mark.parametrize(
    ("model_id", "revision"),
    [
        ("another-256d-model", DEFAULT_SPEAKER_MODEL_REVISION),
        (DEFAULT_SPEAKER_MODEL_ID, "another-checkpoint"),
    ],
)
def test_same_dimension_different_model_or_revision_still_requires_migration(
    tmp_path, model_id, revision
):
    registry, folder = make_profile(tmp_path, dimension=256, model_id=model_id, revision=revision)
    profiles = registry.load(["person"])
    assert registry._encoder.calls == 1
    assert profiles[0].embedding[0] == 1
    assert (
        json.loads((folder / "profile.json").read_text())["model_revision"]
        == DEFAULT_SPEAKER_MODEL_REVISION
    )


def test_missing_audio_preserves_incompatible_profile(tmp_path):
    registry, folder = make_profile(tmp_path, audio=False)
    before = {file: (folder / file).read_bytes() for file in ("profile.json", "embedding.npy")}
    with pytest.raises(ValueError, match="thiếu mẫu âm thanh hợp lệ"):
        registry.load(["person"])
    assert registry._encoder.calls == 0
    assert all((folder / file).read_bytes() == value for file, value in before.items())


def test_invalid_encoder_result_does_not_replace_existing_profile(tmp_path):
    registry, folder = make_profile(tmp_path)
    registry._encoder.encode = lambda wave: np.zeros(192, dtype=np.float32)
    before = {file: (folder / file).read_bytes() for file in ("profile.json", "embedding.npy")}
    with pytest.raises(ValueError, match="embedding không hợp lệ"):
        registry.load(["person"])
    assert all((folder / file).read_bytes() == value for file, value in before.items())
