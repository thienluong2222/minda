"""Two-stream separation restricted to detected overlap intervals."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import torch
import torchaudio
from scipy.signal import resample_poly
from speechbrain.inference.separation import SepformerSeparation
from speechbrain.utils.fetching import FetchConfig


class TwoSpeakerSeparator:
    """Load pinned SepFormer lazily and return tracks at the analysis sample rate."""

    def __init__(
        self,
        model_id: str,
        revision: str,
        model_cache_dir: Path,
        runtime_dir: Path,
        sample_rate: int = 16000,
        separator_sample_rate: int = 8000,
    ) -> None:
        self.model_id = model_id
        self.revision = revision
        self.model_cache_dir = model_cache_dir
        self.runtime_dir = runtime_dir
        self.sample_rate = sample_rate
        self.separator_sample_rate = separator_sample_rate
        self._model: SepformerSeparation | None = None

    def _load(self) -> SepformerSeparation:
        if self._model is None:
            self._model = SepformerSeparation.from_hparams(
                source=self.model_id,
                savedir=self.runtime_dir,
                run_opts={"device": "cpu"},
                fetch_config=FetchConfig(
                    allow_network=False,
                    revision=self.revision,
                    huggingface_cache_dir=self.model_cache_dir,
                ),
            )
        return self._model

    def separate(
        self,
        signal: np.ndarray[Any, np.dtype[np.float32]],
        start_sec: float,
        end_sec: float,
        context_sec: float,
    ) -> list[np.ndarray[Any, np.dtype[np.float32]]]:
        """Use context for inference but crop both output streams to the overlap."""
        start = max(0, round(start_sec * self.sample_rate))
        end = min(len(signal), round(end_sec * self.sample_rate))
        context_start = max(0, start - round(context_sec * self.sample_rate))
        context_end = min(len(signal), end + round(context_sec * self.sample_rate))
        if end <= start or context_end <= context_start:
            raise ValueError("Empty overlap interval")
        expanded = np.asarray(signal[context_start:context_end], dtype=np.float32)
        tensor = torch.from_numpy(expanded).unsqueeze(0)
        at_model_rate = torchaudio.functional.resample(
            tensor, self.sample_rate, self.separator_sample_rate
        )
        separated = self._load().separate_batch(at_model_rate).squeeze(0).detach().cpu().numpy()
        if separated.ndim != 2 or separated.shape[1] != 2:
            raise ValueError(f"Expected two separated tracks, got {separated.shape}")
        crop_start = start - context_start
        length = end - start
        result = []
        for stream in range(2):
            resampled = resample_poly(
                separated[:, stream], self.sample_rate, self.separator_sample_rate
            ).astype(np.float32)
            cropped = resampled[crop_start : crop_start + length]
            if len(cropped) < length:
                cropped = np.pad(cropped, (0, length - len(cropped)))
            result.append(np.asarray(cropped, dtype=np.float32))
        return result
