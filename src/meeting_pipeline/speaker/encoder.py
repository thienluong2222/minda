"""Offline SpeechBrain ECAPA-TDNN speaker encoder for meeting pipeline.

Specification: Section 3.2 & 10.1 of docs/PLAN_VIVOS_SYNTHETIC_PIPELINE.md.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, cast

import numpy as np
import torch

logger = logging.getLogger(__name__)


class ECAPAEncoder:
    """Offline 192-dimensional ECAPA-TDNN speaker encoder using SpeechBrain."""

    def __init__(
        self,
        model_id: str = "speechbrain/spkrec-ecapa-voxceleb",
        revision: str = "0f99f2d0ebe89ac095bcc5903c4dd8f72b367286",
        cache_dir: Path | str = "data/model_cache",
        device: str = "cpu",
    ) -> None:
        self.model_id = model_id
        self.revision = revision
        self.cache_dir = Path(cache_dir)
        self.device = device
        self._classifier: Any = None

    def _load(self) -> None:
        if self._classifier is not None:
            return

        from speechbrain.inference.speaker import EncoderClassifier
        from speechbrain.utils.fetching import FetchConfig

        snapshot_dir = (
            self.cache_dir
            / f"models--{self.model_id.replace('/', '--')}"
            / "snapshots"
            / self.revision
        )
        if not snapshot_dir.is_dir():
            raise FileNotFoundError(f"ECAPA snapshot not found at {snapshot_dir}.")

        runtime_dir = Path("data/runtime/ecapa_pipeline")
        runtime_dir.mkdir(parents=True, exist_ok=True)

        self._classifier = EncoderClassifier.from_hparams(
            source=str(snapshot_dir),
            savedir=str(runtime_dir),
            run_opts={"device": self.device},
            overrides={"pretrained_path": str(snapshot_dir)},
            fetch_config=FetchConfig(allow_network=False),
        )

    def encode(
        self,
        waveform: np.ndarray[Any, np.dtype[np.float32]],
    ) -> np.ndarray[Any, np.dtype[np.float32]]:
        """Encode 1D float32 audio waveform into a 192-dim normalized embedding."""
        self._load()
        if waveform.ndim != 1:
            raise ValueError(f"Expected 1D audio waveform, got shape {waveform.shape}")

        tensor = torch.from_numpy(waveform.astype(np.float32)).unsqueeze(0).to(self.device)
        with torch.inference_mode():
            emb = self._classifier.encode_batch(tensor)
            emb_np = emb.squeeze().detach().cpu().numpy().astype(np.float32)

        norm = float(np.linalg.norm(emb_np))
        if norm > 1e-8:
            emb_np = emb_np / norm
        return cast(np.ndarray[Any, np.dtype[np.float32]], emb_np)
