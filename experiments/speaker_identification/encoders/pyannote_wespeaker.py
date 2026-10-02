"""WeSpeaker ResNet34-LM speaker encoder adapter using pyannote.audio."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import torch

from experiments.speaker_identification.encoders.base import BaseSpeakerEncoder


class PyannoteWeSpeakerEncoder(BaseSpeakerEncoder):
    """WeSpeaker ResNet34-LM 256-dim speaker encoder (E3)."""

    def __init__(
        self,
        encoder_id: str = "E3",
        model_id: str = "pyannote/wespeaker-voxceleb-resnet34-LM",
        model_revision: str = "837717ddb9ff5507820346191109dc79c958d614",
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
        self.embedding_dimension = 256

        self._inference: Any = None

    def _load_model(self) -> None:
        if self._inference is not None:
            return

        from pyannote.audio import Inference, Model
        from pyannote.audio.core.task import (
            Problem,
            Resolution,
            Specifications,
        )

        # PyTorch 2.6 safe globals for PyTorch Lightning / pyannote checkpoint loading
        torch.serialization.add_safe_globals(
            [torch.torch_version.TorchVersion, Specifications, Problem, Resolution]
        )

        snapshot_dir = (
            self.cache_dir
            / f"models--{self.model_id.replace('/', '--')}"
            / "snapshots"
            / self.model_revision
        )
        bin_file = snapshot_dir / "pytorch_model.bin"
        cfg_file = snapshot_dir / "config.yaml"

        if not bin_file.is_file() or not cfg_file.is_file():
            raise FileNotFoundError(
                f"WeSpeaker model files not found at {snapshot_dir}. "
                f"Run `prepare-models` to download revision {self.model_revision}."
            )

        model = Model.from_pretrained(str(bin_file), hparams_file=str(cfg_file))
        model.to(torch.device(self.device))
        model.eval()
        self._inference = Inference(model, window="whole", device=torch.device(self.device))

    def _encode_internal(self, waveform: np.ndarray) -> np.ndarray:
        self._load_model()
        tensor = torch.from_numpy(waveform.astype(np.float32)).unsqueeze(0)
        emb = self._inference({"waveform": tensor, "sample_rate": self.sample_rate})
        return np.asarray(emb, dtype=np.float32).reshape(-1)
