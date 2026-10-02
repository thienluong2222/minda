"""Simple disk-backed speaker enrollment for the local demo."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from speechbrain.inference.speaker import EncoderClassifier
from speechbrain.utils.fetching import FetchConfig

from meeting_pipeline.adapters.audio_io import decode_mono
from meeting_pipeline.config import PipelineConfig


@dataclass(frozen=True, slots=True)
class SpeakerProfileInput:
    """Named speaker prototype supplied to one pipeline run."""

    speaker_id: str
    display_name: str
    embedding: np.ndarray
    sample_waveforms: tuple[np.ndarray, ...] = ()


class SpeakerRegistry:
    """Create and load immutable-enough demo profiles without requiring the full DB UI."""

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self.root = config.paths.data_dir / "speakers"
        self._encoder: EncoderClassifier | None = None

    def list_profiles(self) -> list[dict[str, object]]:
        profiles = []
        for path in self.root.glob("*/profile.json"):
            profiles.append(dict(json.loads(path.read_text(encoding="utf-8"))))
        return sorted(profiles, key=lambda item: str(item["display_name"]).casefold())

    def enroll(self, display_name: str, samples: list[Path]) -> dict[str, object]:
        name = display_name.strip()
        if not name:
            raise ValueError("Tên người tham gia không được để trống")
        if not samples:
            raise ValueError("Cần ít nhất một mẫu giọng")
        speaker_id = str(uuid.uuid4())
        speaker_dir = self.root / speaker_id
        decoded_dir = speaker_dir / "decoded"
        decoded_dir.mkdir(parents=True, exist_ok=False)
        embeddings: list[np.ndarray] = []
        total_seconds = 0.0
        for index, sample in enumerate(samples, start=1):
            decoded = decoded_dir / f"sample-{index}.wav"
            decode_mono(sample, decoded, self.config.audio.analysis_sample_rate)
            waveform, rate = sf.read(decoded, dtype="float32")
            if rate != self.config.audio.analysis_sample_rate or waveform.size < rate:
                raise ValueError(f"Mẫu giọng quá ngắn: {sample.name}")
            total_seconds += waveform.size / rate
            embeddings.append(self.encode(waveform))
        prototype = np.mean(np.stack(embeddings), axis=0)
        prototype /= max(float(np.linalg.norm(prototype)), 1e-12)
        np.save(speaker_dir / "embedding.npy", prototype.astype(np.float32))
        profile: dict[str, object] = {
            "speaker_id": speaker_id,
            "display_name": name,
            "sample_count": len(samples),
            "total_seconds": total_seconds,
            "model_id": str(self.config.identity["model_id"]),
            "model_revision": str(self.config.identity["model_revision"]),
        }
        (speaker_dir / "profile.json").write_text(
            json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return profile

    def load(self, speaker_ids: list[str]) -> list[SpeakerProfileInput]:
        profiles = []
        for speaker_id in speaker_ids:
            speaker_dir = self.root / speaker_id
            metadata_path = speaker_dir / "profile.json"
            embedding_path = speaker_dir / "embedding.npy"
            if not metadata_path.is_file() or not embedding_path.is_file():
                continue
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            samples: list[np.ndarray] = []
            decoded_dir = speaker_dir / "decoded"
            if decoded_dir.is_dir():
                for sample_path in sorted(decoded_dir.glob("sample-*.wav")):
                    try:
                        wave, rate = sf.read(sample_path, dtype="float32")
                        if rate == self.config.audio.analysis_sample_rate and wave.ndim == 1:
                            samples.append(wave)
                    except Exception:
                        pass
            profiles.append(
                SpeakerProfileInput(
                    speaker_id,
                    str(metadata["display_name"]),
                    np.asarray(np.load(embedding_path), dtype=np.float32),
                    sample_waveforms=tuple(samples),
                )
            )
        return profiles

    def encode(self, waveform: np.ndarray) -> np.ndarray:
        if self._encoder is None:
            revision = str(self.config.identity["model_revision"])
            snapshot = (
                self.config.paths.model_cache_dir
                / "models--speechbrain--spkrec-ecapa-voxceleb"
                / "snapshots"
                / revision
            )
            if not snapshot.is_dir():
                raise FileNotFoundError("ECAPA snapshot chưa được chuẩn bị")
            self._encoder = EncoderClassifier.from_hparams(
                source=str(snapshot),
                savedir=self.config.paths.data_dir / "runtime" / "ecapa",
                run_opts={"device": "cpu"},
                overrides={"pretrained_path": str(snapshot)},
                fetch_config=FetchConfig(allow_network=False),
            )
        tensor = torch.from_numpy(np.asarray(waveform, dtype=np.float32)).unsqueeze(0)
        with torch.inference_mode():
            embedding = self._encoder.encode_batch(tensor).squeeze().detach().cpu().numpy()
        vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
        return vector / max(float(np.linalg.norm(vector)), 1e-12)
