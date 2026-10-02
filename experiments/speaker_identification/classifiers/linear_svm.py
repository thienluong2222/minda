"""Linear SVM classifier backend."""

from __future__ import annotations

import numpy as np
from sklearn.svm import LinearSVC  # type: ignore[import-untyped]

from experiments.speaker_identification.classifiers.base import BaseClassifier
from experiments.speaker_identification.contracts import ClassifierPrediction


class LinearSVMClassifier(BaseClassifier):
    """Linear Support Vector Classifier backend."""

    classifier_id: str = "linear_svm"

    def __init__(self, c: float = 1.0) -> None:
        self.c = c
        self._clf: LinearSVC | None = None
        self._classes: list[str] = []

    def fit(self, support_embeddings: dict[str, list[np.ndarray]]) -> None:
        X: list[np.ndarray] = []
        y: list[str] = []

        for spk_id, embs in support_embeddings.items():
            for emb in embs:
                X.append(emb)
                y.append(spk_id)

        if not X:
            raise ValueError("No support embeddings provided to fit LinearSVMClassifier")

        self._classes = sorted(list(support_embeddings.keys()))
        self._clf = LinearSVC(
            C=self.c,
            loss="squared_hinge",
            random_state=42,
            max_iter=2000,
        )
        self._clf.fit(np.asarray(X), np.asarray(y))

    def predict(
        self,
        query_embedding: np.ndarray,
        score_threshold: float = 0.0,
        margin_threshold: float = 0.0,
        is_open_set: bool = False,
    ) -> ClassifierPrediction:
        if self._clf is None:
            raise RuntimeError("Classifier has not been fitted")

        q = query_embedding.reshape(1, -1)
        raw_decision = self._clf.decision_function(q)

        classes = list(self._clf.classes_)
        if raw_decision.ndim == 1:
            # Binary classification case
            score = float(raw_decision[0])
            scores = [(classes[1], score), (classes[0], -score)]
        else:
            scores = [(classes[i], float(raw_decision[0, i])) for i in range(len(classes))]

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
