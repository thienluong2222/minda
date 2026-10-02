"""Cosine prototype classifier backend."""

from __future__ import annotations

import numpy as np

from experiments.speaker_identification.classifiers.base import BaseClassifier
from experiments.speaker_identification.contracts import ClassifierPrediction


class CosinePrototypeClassifier(BaseClassifier):
    """Classifier using L2-normalized cosine prototype centroid per speaker."""

    classifier_id: str = "cosine_prototype"

    def __init__(self) -> None:
        self.prototypes: dict[str, np.ndarray] = {}

    def fit(self, support_embeddings: dict[str, list[np.ndarray]]) -> None:
        self.prototypes.clear()
        for spk_id, embs in support_embeddings.items():
            if not embs:
                continue
            stacked = np.stack(embs)
            centroid = np.mean(stacked, axis=0)
            norm = float(np.linalg.norm(centroid))
            self.prototypes[spk_id] = (centroid / max(norm, 1e-12)).astype(np.float32)

    def predict(
        self,
        query_embedding: np.ndarray,
        score_threshold: float = 0.0,
        margin_threshold: float = 0.0,
        is_open_set: bool = False,
    ) -> ClassifierPrediction:
        if not self.prototypes:
            raise RuntimeError("Classifier has not been fitted with any support embeddings")

        scores: list[tuple[str, float]] = []
        for spk_id, proto in self.prototypes.items():
            score = float(np.dot(query_embedding, proto))
            scores.append((spk_id, score))

        scores.sort(key=lambda item: item[1], reverse=True)

        top1_spk, top1_score = scores[0]
        top2_score = scores[1][1] if len(scores) > 1 else -1.0
        margin = top1_score - top2_score

        is_unknown = False
        if is_open_set:
            if top1_score < score_threshold or margin < margin_threshold:
                is_unknown = True

        pred_spk = "unknown" if is_unknown else top1_spk

        return ClassifierPrediction(
            predicted_speaker_id=pred_spk,
            predicted_unknown=is_unknown,
            top1_score=top1_score,
            top2_score=top2_score,
            margin=margin,
            top_candidates=scores[:3],
        )
