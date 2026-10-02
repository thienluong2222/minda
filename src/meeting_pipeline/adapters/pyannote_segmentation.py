"""Pinned pyannote segmentation adapter for the legacy 3.0 checkpoint."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import torch
from pyannote.audio import Inference, Model
from pyannote.audio.core.task import Problem, Resolution, Specifications
from torch.torch_version import TorchVersion

from meeting_pipeline.domain.errors import ModelUnavailableError


class PyannoteSegmentationAdapter:
    """Load and run the official pinned segmentation-3.0 checkpoint on CPU.

    Torch 2.6 defaults to a restricted weights-only loader. The legacy Lightning
    checkpoint contains four metadata classes in addition to tensors. They are
    explicitly allowlisted rather than disabling the restriction globally.
    """

    def __init__(self, checkpoint_path: Path, step_seconds: float = 2.5) -> None:
        self.checkpoint_path = checkpoint_path
        self.step_seconds = step_seconds
        self._inference: Inference | None = None

    def load(self) -> None:
        """Load lazily after verifying the configured checkpoint exists locally."""
        if not self.checkpoint_path.is_file():
            raise ModelUnavailableError(f"Missing pyannote checkpoint: {self.checkpoint_path}")
        with torch.serialization.safe_globals([TorchVersion, Resolution, Specifications, Problem]):
            model = Model.from_pretrained(self.checkpoint_path, map_location="cpu")
        self._inference = Inference(model, duration=10.0, step=self.step_seconds)

    def segment_file(self, audio_path: Path) -> Any:
        """Return pyannote sliding-window powerset scores for 16 kHz mono audio."""
        if self._inference is None:
            self.load()
        if self._inference is None:
            raise ModelUnavailableError("Pyannote inference failed to initialize")
        return self._inference(str(audio_path))
