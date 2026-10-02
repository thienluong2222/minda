"""Unit tests specifically verifying open-set rejection and margin thresholds."""

from __future__ import annotations

import numpy as np

from experiments.speaker_identification.classifiers.cosine_prototype import (
    CosinePrototypeClassifier,
)


def test_open_set_rejection_low_score() -> None:
    # 2 known speakers
    proto_a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    proto_b = np.array([0.0, 1.0, 0.0], dtype=np.float32)

    support = {"spk_a": [proto_a], "spk_b": [proto_b]}
    clf = CosinePrototypeClassifier()
    clf.fit(support)

    # Unknown speaker orthogonal to both
    query_unknown = np.array([0.0, 0.0, 1.0], dtype=np.float32)

    # 1. Closed-set must assign to one known speaker
    pred_closed = clf.predict(query_unknown, is_open_set=False)
    assert pred_closed.predicted_speaker_id in ("spk_a", "spk_b")
    assert not pred_closed.predicted_unknown

    # 2. Open-set with threshold=0.5 must reject to unknown
    pred_open = clf.predict(
        query_unknown, score_threshold=0.5, margin_threshold=0.0, is_open_set=True
    )
    assert pred_open.predicted_speaker_id == "unknown"
    assert pred_open.predicted_unknown


def test_open_set_rejection_ambiguous_margin() -> None:
    # 2 known speakers
    proto_a = np.array([1.0, 0.0], dtype=np.float32)
    proto_b = np.array([0.0, 1.0], dtype=np.float32)

    support = {"spk_a": [proto_a], "spk_b": [proto_b]}
    clf = CosinePrototypeClassifier()
    clf.fit(support)

    # Query directly in the middle between spk_a and spk_b (score ~0.707 each)
    query_ambiguous = np.array([1.0, 1.0], dtype=np.float32)
    query_ambiguous /= np.linalg.norm(query_ambiguous)

    # Score is high (~0.707 >= 0.50), but margin is nearly 0 (< 0.10)
    pred = clf.predict(
        query_ambiguous,
        score_threshold=0.50,
        margin_threshold=0.10,
        is_open_set=True,
    )
    assert pred.predicted_speaker_id == "unknown"
    assert pred.predicted_unknown
    assert pred.margin < 0.05


def test_open_set_acceptance_clear_known() -> None:
    proto_a = np.array([1.0, 0.0], dtype=np.float32)
    proto_b = np.array([0.0, 1.0], dtype=np.float32)

    support = {"spk_a": [proto_a], "spk_b": [proto_b]}
    clf = CosinePrototypeClassifier()
    clf.fit(support)

    query_clear = np.array([0.98, 0.05], dtype=np.float32)
    query_clear /= np.linalg.norm(query_clear)

    pred = clf.predict(
        query_clear,
        score_threshold=0.50,
        margin_threshold=0.10,
        is_open_set=True,
    )
    assert pred.predicted_speaker_id == "spk_a"
    assert not pred.predicted_unknown
    assert pred.top1_score > 0.90
    assert pred.margin > 0.80
