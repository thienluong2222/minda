"""Base interface for speaker classifiers."""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from experiments.speaker_identification.contracts import ClassifierPrediction


class BaseClassifier(ABC):
    """Abstract base class for closed-set and open-set speaker classifiers."""

    classifier_id: str

    @abstractmethod
    def fit(self, support_embeddings: dict[str, list[np.ndarray]]) -> None:
        """Fit classifier on support embeddings per speaker."""
        raise NotImplementedError

    @abstractmethod
    def predict(
        self,
        query_embedding: np.ndarray,
        score_threshold: float = 0.0,
        margin_threshold: float = 0.0,
        is_open_set: bool = False,
    ) -> ClassifierPrediction:
        """Predict speaker identity or 'unknown' for a query embedding."""
        raise NotImplementedError
