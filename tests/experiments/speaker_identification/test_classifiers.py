"""Unit tests for speaker classifiers."""

from __future__ import annotations

import numpy as np
import pytest

from experiments.speaker_identification.classifiers.cosine_knn import CosineKNNClassifier
from experiments.speaker_identification.classifiers.cosine_prototype import (
    CosinePrototypeClassifier,
)
from experiments.speaker_identification.classifiers.linear_svm import LinearSVMClassifier


@pytest.fixture
def synthetic_data() -> tuple[dict[str, list[np.ndarray]], np.ndarray]:
    """Create distinct orthogonal unit vectors for 3 speakers."""
    # 3 speakers in 3D space
    spk_a_v1 = np.array([1.0, 0.1, 0.0], dtype=np.float32)
    spk_a_v1 /= np.linalg.norm(spk_a_v1)
    spk_a_v2 = np.array([1.0, -0.1, 0.0], dtype=np.float32)
    spk_a_v2 /= np.linalg.norm(spk_a_v2)

    spk_b_v1 = np.array([0.0, 1.0, 0.1], dtype=np.float32)
    spk_b_v1 /= np.linalg.norm(spk_b_v1)
    spk_b_v2 = np.array([0.0, 1.0, -0.1], dtype=np.float32)
    spk_b_v2 /= np.linalg.norm(spk_b_v2)

    spk_c_v1 = np.array([0.0, 0.1, 1.0], dtype=np.float32)
    spk_c_v1 /= np.linalg.norm(spk_c_v1)
    spk_c_v2 = np.array([0.0, -0.1, 1.0], dtype=np.float32)
    spk_c_v2 /= np.linalg.norm(spk_c_v2)

    support = {
        "spk_a": [spk_a_v1, spk_a_v2],
        "spk_b": [spk_b_v1, spk_b_v2],
        "spk_c": [spk_c_v1, spk_c_v2],
    }
    # Query very close to spk_a
    query = np.array([0.99, 0.05, 0.0], dtype=np.float32)
    query /= np.linalg.norm(query)
    return support, query


def test_cosine_prototype(synthetic_data: tuple[dict[str, list[np.ndarray]], np.ndarray]) -> None:
    support, query = synthetic_data
    clf = CosinePrototypeClassifier()
    clf.fit(support)

    pred_closed = clf.predict(query, is_open_set=False)
    assert pred_closed.predicted_speaker_id == "spk_a"
    assert not pred_closed.predicted_unknown
    assert pred_closed.top1_score > 0.95
    assert pred_closed.margin > 0.8


def test_cosine_knn(synthetic_data: tuple[dict[str, list[np.ndarray]], np.ndarray]) -> None:
    support, query = synthetic_data
    clf = CosineKNNClassifier(n_neighbors=3)
    clf.fit(support)

    pred_closed = clf.predict(query, is_open_set=False)
    assert pred_closed.predicted_speaker_id == "spk_a"
    assert not pred_closed.predicted_unknown
    assert pred_closed.top1_score > 0.95


def test_linear_svm(synthetic_data: tuple[dict[str, list[np.ndarray]], np.ndarray]) -> None:
    support, query = synthetic_data
    clf = LinearSVMClassifier(c=1.0)
    clf.fit(support)

    pred_closed = clf.predict(query, is_open_set=False)
    assert pred_closed.predicted_speaker_id == "spk_a"
    assert not pred_closed.predicted_unknown
