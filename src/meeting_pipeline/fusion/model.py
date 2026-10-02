"""Learned fusion model (F6_LEARNED) using regularized Logistic Regression.

Specification: Section 13.1 & 13.3 of docs/PLAN_VIVOS_SYNTHETIC_PIPELINE.md.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import joblib  # type: ignore[import-untyped]
import numpy as np
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]
from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


class LearnedFusionModel:
    """Logistic Regression classifier estimating correctness probability of candidate tokens."""

    def __init__(self, c_regularization: float = 1.0, seed: int = 42) -> None:
        self.c_regularization = c_regularization
        self.seed = seed
        self.scaler = StandardScaler()
        self.model = LogisticRegression(
            C=self.c_regularization,
            class_weight="balanced",
            max_iter=500,
            random_state=self.seed,
        )
        self.is_fitted = False

    def fit(
        self,
        x_features: np.ndarray[Any, np.dtype[np.float32]],
        y_labels: np.ndarray[Any, np.dtype[np.int32]],
    ) -> None:
        """Fit scaler and logistic regression model on training data."""
        if len(x_features) < 10 or len(np.unique(y_labels)) < 2:
            logger.warning("Insufficient samples or single class; model not fitted")
            return

        x_scaled = self.scaler.fit_transform(x_features)
        self.model.fit(x_scaled, y_labels)
        self.is_fitted = True

    def predict_token_score(self, features: np.ndarray[Any, np.dtype[np.float32]]) -> float:
        """Predict correctness probability in [0.0, 1.0] for a feature vector."""
        if not self.is_fitted:
            # Fallback heuristic: weighted combination of audio_quality and asr_confidence
            # features: [audio_quality, asr_confidence, no_speech, agreement, len, dur]
            if len(features) >= 4:
                return float(0.4 * features[0] + 0.4 * features[1] + 0.2 * features[3])
            return 0.5

        feats_2d = features.reshape(1, -1)
        scaled = self.scaler.transform(feats_2d)
        proba = self.model.predict_proba(scaled)[0, 1]
        return float(proba)

    def save(self, model_path: Path | str) -> None:
        """Save model and scaler to disk."""
        p = Path(model_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"scaler": self.scaler, "model": self.model, "fitted": self.is_fitted}, p)

    @classmethod
    def load(cls, model_path: Path | str) -> LearnedFusionModel:
        """Load trained model from disk."""
        p = Path(model_path)
        if not p.exists():
            return cls()
        data = joblib.load(p)
        inst = cls()
        inst.scaler = data["scaler"]
        inst.model = data["model"]
        inst.is_fitted = data["fitted"]
        return inst
