"""Pinned pyannote segmentation adapter for the legacy 3.0 checkpoint with caching."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import torch
from pyannote.audio import Inference, Model
from pyannote.audio.core.task import Problem, Resolution, Specifications
from torch.torch_version import TorchVersion

from meeting_pipeline.adapters.audio_io import sha256_file
from meeting_pipeline.domain.errors import ModelUnavailableError


@dataclass(slots=True)
class SlidingWindow:
    """Sliding window representation compatible with pyannote's SlidingWindowFeature."""

    duration: float
    step: float

    def __getitem__(self, index: int) -> SimpleNamespace:
        return SimpleNamespace(start=float(index * self.step))


@dataclass(slots=True)
class SegmentationResult:
    """Structured, cacheable inference output from pyannote segmentation."""

    data: np.ndarray
    sliding_window: SlidingWindow
    source_id: str = ""
    audio_hash: str = ""
    model_revision: str = "3.0"
    step_seconds: float = 2.5
    sample_rate: int = 16000
    duration_sec: float = 0.0
    frame_step: float = 0.016875
    raw_scores: Any | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "audio_hash": self.audio_hash,
            "model_revision": self.model_revision,
            "step_seconds": self.step_seconds,
            "sample_rate": self.sample_rate,
            "duration_sec": self.duration_sec,
            "frame_step": self.frame_step,
            "shape": list(self.data.shape),
        }


class PyannoteSegmentationAdapter:
    """Load and run the official pinned segmentation-3.0 checkpoint on CPU with caching.

    Torch 2.6 defaults to a restricted weights-only loader. The legacy Lightning
    checkpoint contains four metadata classes in addition to tensors. They are
    explicitly allowlisted rather than disabling the restriction globally.
    """

    def __init__(
        self,
        checkpoint_path: Path,
        step_seconds: float = 2.5,
        model_revision: str = "3.0",
    ) -> None:
        self.checkpoint_path = checkpoint_path
        self.step_seconds = step_seconds
        self.model_revision = model_revision
        self._inference: Inference | None = None
        self._cache: dict[str, SegmentationResult] = {}
        self.call_count: int = 0

    def load(self) -> None:
        """Load lazily after verifying the configured checkpoint exists locally."""
        if not self.checkpoint_path.is_file():
            raise ModelUnavailableError(f"Missing pyannote checkpoint: {self.checkpoint_path}")
        with torch.serialization.safe_globals([TorchVersion, Resolution, Specifications, Problem]):
            model = Model.from_pretrained(self.checkpoint_path, map_location="cpu")
        self._inference = Inference(model, duration=10.0, step=self.step_seconds)

    def _compute_file_hash(self, path: Path) -> str:
        try:
            return sha256_file(path)
        except Exception:
            return hashlib.sha256(str(path).encode("utf-8")).hexdigest()

    def segment_file(self, audio_path: Path, source_id: str = "") -> SegmentationResult:
        """Return cached or computed pyannote sliding-window multilabel scores."""
        audio_hash = self._compute_file_hash(audio_path)
        cache_key = f"{audio_hash}:{self.step_seconds}:{self.model_revision}"

        if cache_key in self._cache:
            cached = self._cache[cache_key]
            if source_id and not cached.source_id:
                cached.source_id = source_id
            return cached

        if self._inference is None:
            self.load()
        if self._inference is None:
            raise ModelUnavailableError("Pyannote inference failed to initialize")

        raw = self._inference(str(audio_path))
        self.call_count += 1

        raw_data = np.asarray(raw.data, dtype=np.float32)
        sw = raw.sliding_window
        duration = float(getattr(sw, "duration", 10.0))
        step = float(getattr(sw, "step", self.step_seconds))
        sliding_window = SlidingWindow(duration=duration, step=step)

        num_chunks = raw_data.shape[0] if raw_data.ndim >= 1 else 0
        num_frames = raw_data.shape[1] if raw_data.ndim >= 2 else 1
        frame_step = duration / max(1, num_frames)
        total_duration = (
            (num_chunks - 1) * step + duration if num_chunks > 0 else 0.0
        )

        result = SegmentationResult(
            data=raw_data,
            sliding_window=sliding_window,
            source_id=source_id,
            audio_hash=audio_hash,
            model_revision=self.model_revision,
            step_seconds=self.step_seconds,
            sample_rate=16000,
            duration_sec=total_duration,
            frame_step=frame_step,
            raw_scores=raw,
        )

        self._cache[cache_key] = result
        return result

    def save_npz(self, path: Path, result: SegmentationResult) -> None:
        """Persist inference output as a lightweight compressed npz artifact."""
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path,
            data=result.data,
            duration=np.float32(result.sliding_window.duration),
            step=np.float32(result.sliding_window.step),
            source_id=result.source_id,
            audio_hash=result.audio_hash,
            model_revision=result.model_revision,
            duration_sec=np.float32(result.duration_sec),
            frame_step=np.float32(result.frame_step),
        )

    def load_npz(self, path: Path) -> SegmentationResult:
        """Load segmentation output from an npz artifact and populate cache."""
        with np.load(path, allow_pickle=False) as npz:
            data = npz["data"]
            duration = float(npz["duration"])
            step = float(npz["step"])
            source_id = str(npz["source_id"])
            audio_hash = str(npz["audio_hash"])
            model_revision = str(npz["model_revision"])
            duration_sec = float(npz["duration_sec"]) if "duration_sec" in npz else 0.0
            frame_step = float(npz["frame_step"]) if "frame_step" in npz else 0.016875

        sliding_window = SlidingWindow(duration=duration, step=step)
        result = SegmentationResult(
            data=data,
            sliding_window=sliding_window,
            source_id=source_id,
            audio_hash=audio_hash,
            model_revision=model_revision,
            step_seconds=step,
            sample_rate=16000,
            duration_sec=duration_sec,
            frame_step=frame_step,
        )
        cache_key = f"{audio_hash}:{step}:{model_revision}"
        self._cache[cache_key] = result
        return result
