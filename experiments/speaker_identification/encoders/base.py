"""Base class and common utilities for speaker encoders."""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from experiments.speaker_identification.audio import validate_waveform


class BaseSpeakerEncoder(ABC):
    """Abstract base class for all speaker encoders."""

    encoder_id: str
    model_id: str
    model_revision: str
    sample_rate: int = 16000
    embedding_dimension: int

    @abstractmethod
    def _encode_internal(self, waveform: np.ndarray) -> np.ndarray:
        """Subclass implementation of encoding logic."""
        raise NotImplementedError

    def encode(self, waveform: np.ndarray) -> np.ndarray:
        """Encode waveform into finite 1D L2-normalized float32 embedding."""
        validate_waveform(waveform)
        raw_emb = self._encode_internal(waveform)

        # Enforce output contract: 1-D, finite, float32, L2-normalized
        emb = np.asarray(raw_emb, dtype=np.float32).reshape(-1)
        if emb.size != self.embedding_dimension:
            raise ValueError(
                f"Encoder {self.encoder_id} returned dimension {emb.size}, "
                f"expected {self.embedding_dimension}"
            )
        if not np.all(np.isfinite(emb)):
            raise ValueError(f"Encoder {self.encoder_id} returned non-finite values (NaN or Inf)")

        norm = float(np.linalg.norm(emb))
        if norm < 1e-12:
            raise ValueError(f"Encoder {self.encoder_id} returned near-zero embedding norm: {norm}")

        return (emb / norm).astype(np.float32)
