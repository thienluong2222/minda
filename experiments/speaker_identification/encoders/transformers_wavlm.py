"""WavLM Base Plus SV speaker encoder adapter using Transformers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import torch

from experiments.speaker_identification.encoders.base import BaseSpeakerEncoder


class TransformersWavLMEncoder(BaseSpeakerEncoder):
    """WavLM Base Plus SV 512-dim speaker encoder (E4)."""

    def __init__(
        self,
        encoder_id: str = "E4",
        model_id: str = "microsoft/wavlm-base-plus-sv",
        model_revision: str = "feb593a6c23c1cc3d9510425c29b0a14d2b07b1e",
        cache_dir: Path | str = "data/model_cache",
        sample_rate: int = 16000,
        device: str = "cpu",
    ) -> None:
        self.encoder_id = encoder_id
        self.model_id = model_id
        self.model_revision = model_revision
        self.cache_dir = Path(cache_dir)
        self.sample_rate = sample_rate
        self.device = device
        self.embedding_dimension = 512

        self._feature_extractor: Any = None
        self._model: Any = None

    def _load_model(self) -> None:
        if self._model is not None:
            return

        from transformers import (
            AutoFeatureExtractor,
            AutoModelForAudioXVector,
        )

        snapshot_dir = (
            self.cache_dir
            / f"models--{self.model_id.replace('/', '--')}"
            / "snapshots"
            / self.model_revision
        )
        if not snapshot_dir.is_dir():
            raise FileNotFoundError(
                f"WavLM snapshot not found at {snapshot_dir}. "
                f"Run `prepare-models` to download revision {self.model_revision}."
            )

        self._feature_extractor = AutoFeatureExtractor.from_pretrained(  # type: ignore[no-untyped-call]
            str(snapshot_dir), local_files_only=True
        )
        self._model = AutoModelForAudioXVector.from_pretrained(
            str(snapshot_dir), local_files_only=True
        )
        self._model.to(torch.device(self.device))
        self._model.eval()

    def _encode_internal(self, waveform: np.ndarray) -> np.ndarray:
        self._load_model()
        inputs = self._feature_extractor(
            waveform.astype(np.float32),
            sampling_rate=self.sample_rate,
            return_tensors="pt",
        )
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        with torch.no_grad():
            outputs = self._model(**inputs)
            emb = outputs.embeddings
            emb_np = emb.squeeze().detach().cpu().numpy()
        return np.asarray(emb_np, dtype=np.float32)
