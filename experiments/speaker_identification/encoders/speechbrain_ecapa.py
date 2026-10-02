"""ECAPA-TDNN speaker encoder adapter using SpeechBrain."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import torch

from experiments.speaker_identification.encoders.base import BaseSpeakerEncoder


class SpeechBrainECAPAEncoder(BaseSpeakerEncoder):
    """ECAPA-TDNN 192-dim speaker encoder (E1)."""

    def __init__(
        self,
        encoder_id: str = "E1",
        model_id: str = "speechbrain/spkrec-ecapa-voxceleb",
        model_revision: str = "0f99f2d0ebe89ac095bcc5903c4dd8f72b367286",
        cache_dir: Path | str = "data/model_cache",
        runtime_dir: Path | str = "data/runtime/ecapa_exp",
        sample_rate: int = 16000,
        device: str = "cpu",
    ) -> None:
        self.encoder_id = encoder_id
        self.model_id = model_id
        self.model_revision = model_revision
        self.cache_dir = Path(cache_dir)
        self.runtime_dir = Path(runtime_dir)
        self.sample_rate = sample_rate
        self.device = device
        self.embedding_dimension = 192

        self._classifier: Any = None

    def _load_model(self) -> None:
        if self._classifier is not None:
            return

        from speechbrain.inference.speaker import EncoderClassifier
        from speechbrain.utils.fetching import FetchConfig

        snapshot_dir = (
            self.cache_dir
            / f"models--{self.model_id.replace('/', '--')}"
            / "snapshots"
            / self.model_revision
        )
        if not snapshot_dir.is_dir():
            raise FileNotFoundError(
                f"ECAPA snapshot not found at {snapshot_dir}. "
                f"Run `prepare-models` to download revision {self.model_revision}."
            )

        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self._classifier = EncoderClassifier.from_hparams(
            source=str(snapshot_dir),
            savedir=str(self.runtime_dir),
            run_opts={"device": self.device},
            overrides={"pretrained_path": str(snapshot_dir)},
            fetch_config=FetchConfig(allow_network=False),
        )

    def _encode_internal(self, waveform: np.ndarray) -> np.ndarray:
        self._load_model()
        tensor = torch.from_numpy(waveform.astype(np.float32)).unsqueeze(0).to(self.device)
        with torch.inference_mode():
            emb = self._classifier.encode_batch(tensor)
            emb_np = emb.squeeze().detach().cpu().numpy()
        return np.asarray(emb_np, dtype=np.float32)
