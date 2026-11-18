"""Offline speaker encoders (SpeechBrain ECAPA-TDNN and pyannote WeSpeaker ResNet34-LM).

Specification: Section 3.2 & 10.1 of docs/PLAN_VIVOS_SYNTHETIC_PIPELINE.md and
WP2 of docs/PLAN_VAD_SPEAKER_ASR_MULTI_SOURCE_2026-10-03.md.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Protocol, cast

import numpy as np
import torch

logger = logging.getLogger(__name__)

DEFAULT_SPEAKER_MODEL_ID = "pyannote/wespeaker-voxceleb-resnet34-LM"
DEFAULT_SPEAKER_MODEL_REVISION = "837717ddb9ff5507820346191109dc79c958d614"


class BaseSpeakerEncoder(Protocol):
    """Protocol for offline speaker embedding encoders."""

    embedding_dimension: int

    def encode(
        self,
        waveform: np.ndarray[Any, np.dtype[np.float32]],
    ) -> np.ndarray[Any, np.dtype[np.float32]]:
        """Encode 1D audio waveform into a normalized speaker embedding."""
        ...


class ECAPAEncoder:
    """Offline 192-dimensional ECAPA-TDNN speaker encoder using SpeechBrain."""

    embedding_dimension: int = 192

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


class WeSpeakerEncoder:
    """Offline 256-dimensional WeSpeaker ResNet34-LM speaker encoder using pyannote."""

    embedding_dimension: int = 256

    def __init__(
        self,
        model_id: str = DEFAULT_SPEAKER_MODEL_ID,
        revision: str = DEFAULT_SPEAKER_MODEL_REVISION,
        cache_dir: Path | str = "data/model_cache",
        device: str = "cpu",
        sample_rate: int = 16000,
    ) -> None:
        self.model_id = model_id
        self.revision = revision
        self.cache_dir = Path(cache_dir)
        self.device = device
        self.sample_rate = sample_rate
        self._inference: Any = None

    def _load(self) -> None:
        if self._inference is not None:
            return

        from pyannote.audio import Inference, Model
        from pyannote.audio.core.task import Problem, Resolution, Specifications

        torch.serialization.add_safe_globals(
            [torch.torch_version.TorchVersion, Specifications, Problem, Resolution]
        )

        snapshot_dir = (
            self.cache_dir
            / f"models--{self.model_id.replace('/', '--')}"
            / "snapshots"
            / self.revision
        )
        bin_file = snapshot_dir / "pytorch_model.bin"
        cfg_file = snapshot_dir / "config.yaml"

        if not bin_file.is_file() or not cfg_file.is_file():
            raise FileNotFoundError(f"WeSpeaker model files not found at {snapshot_dir}.")

        model = Model.from_pretrained(str(bin_file), hparams_file=str(cfg_file))
        model.to(torch.device(self.device))
        model.eval()
        self._inference = Inference(model, window="whole", device=torch.device(self.device))

    def encode(
        self,
        waveform: np.ndarray[Any, np.dtype[np.float32]],
    ) -> np.ndarray[Any, np.dtype[np.float32]]:
        """Encode 1D float32 audio waveform into a 256-dim normalized embedding."""
        self._load()
        if waveform.ndim != 1:
            raise ValueError(f"Expected 1D audio waveform, got shape {waveform.shape}")

        tensor = torch.from_numpy(waveform.astype(np.float32)).unsqueeze(0)
        emb = self._inference({"waveform": tensor, "sample_rate": self.sample_rate})
        emb_np = np.asarray(emb, dtype=np.float32).reshape(-1)

        norm = float(np.linalg.norm(emb_np))
        if norm > 1e-8:
            emb_np = emb_np / norm
        return cast(np.ndarray[Any, np.dtype[np.float32]], emb_np)


def create_speaker_encoder(
    model_id: str = DEFAULT_SPEAKER_MODEL_ID,
    revision: str = DEFAULT_SPEAKER_MODEL_REVISION,
    cache_dir: Path | str = "data/model_cache",
    device: str = "cpu",
    encoder_type: str = "",
) -> ECAPAEncoder | WeSpeakerEncoder:
    """Factory to instantiate the appropriate speaker encoder."""
    if encoder_type.lower() == "wespeaker" or "wespeaker" in model_id.lower():
        return WeSpeakerEncoder(
            model_id=model_id,
            revision=revision,
            cache_dir=cache_dir,
            device=device,
        )
    return ECAPAEncoder(
        model_id=model_id,
        revision=revision,
        cache_dir=cache_dir,
        device=device,
    )
