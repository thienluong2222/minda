"""Cosine K-Nearest Neighbors classifier backend."""

from __future__ import annotations

import numpy as np
from sklearn.neighbors import KNeighborsClassifier  # type: ignore[import-untyped]

from experiments.speaker_identification.classifiers.base import BaseClassifier
from experiments.speaker_identification.contracts import ClassifierPrediction


class CosineKNNClassifier(BaseClassifier):
    """K-Nearest Neighbors classifier using cosine metric."""

    classifier_id: str = "cosine_knn"

    def __init__(self, n_neighbors: int = 3) -> None:
        self.requested_n_neighbors = n_neighbors
        self.n_neighbors = n_neighbors
        self._knn: KNeighborsClassifier | None = None
        self._classes: list[str] = []
        self._X_by_speaker: dict[str, list[np.ndarray]] = {}

    def fit(self, support_embeddings: dict[str, list[np.ndarray]]) -> None:
        self._X_by_speaker = {k: list(v) for k, v in support_embeddings.items() if v}
        X: list[np.ndarray] = []
        y: list[str] = []

        for spk_id, embs in self._X_by_speaker.items():
            for emb in embs:
                X.append(emb)
                y.append(spk_id)

        if not X:
            raise ValueError("No support embeddings provided to fit CosineKNNClassifier")

        self._classes = sorted(list(self._X_by_speaker.keys()))
        total_vectors = len(X)
        self.n_neighbors = min(self.requested_n_neighbors, total_vectors)

        self._knn = KNeighborsClassifier(
            n_neighbors=self.n_neighbors,
            metric="cosine",
            weights="distance",
        )
        self._knn.fit(np.asarray(X), np.asarray(y))

    def predict(
        self,
        query_embedding: np.ndarray,
        score_threshold: float = 0.0,
        margin_threshold: float = 0.0,
        is_open_set: bool = False,
    ) -> ClassifierPrediction:
        if self._knn is None:
            raise RuntimeError("Classifier has not been fitted")

        q = query_embedding.reshape(1, -1)
        knn_pred = str(self._knn.predict(q)[0])

        # Compute nearest distance / maximum similarity per class
        class_sims: list[tuple[str, float]] = []
        for spk_id, embs in self._X_by_speaker.items():
            # Dot products since vectors are L2-normalized
            stacked = np.stack(embs)
            dots = np.dot(stacked, query_embedding)
            max_sim = float(np.max(dots))
            class_sims.append((spk_id, max_sim))

        class_sims.sort(key=lambda item: item[1], reverse=True)

        _, top1_score = class_sims[0]
        top2_score = class_sims[1][1] if len(class_sims) > 1 else -1.0
        margin = top1_score - top2_score

        is_unknown = False
        if is_open_set:
            if top1_score < score_threshold or margin < margin_threshold:
                is_unknown = True

        pred_spk = "unknown" if is_unknown else knn_pred

        return ClassifierPrediction(
            predicted_speaker_id=pred_spk,
            predicted_unknown=is_unknown,
            top1_score=top1_score,
            top2_score=top2_score,
            margin=margin,
            top_candidates=class_sims[:3],
        )
