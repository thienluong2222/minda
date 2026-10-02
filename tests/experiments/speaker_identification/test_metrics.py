"""Unit tests for closed-set and open-set metric calculations."""

from __future__ import annotations

import pytest

from experiments.speaker_identification.metrics import (
    aggregate_episode_metrics,
    compute_closed_set_metrics,
    compute_open_set_metrics,
)


def test_closed_set_perfect_accuracy() -> None:
    y_true = ["spk1", "spk1", "spk2", "spk2"]
    y_pred = ["spk1", "spk1", "spk2", "spk2"]
    labels = ["spk1", "spk2"]

    res = compute_closed_set_metrics(y_true, y_pred, labels)
    assert res["accuracy"] == 1.0
    assert res["macro_precision"] == 1.0
    assert res["macro_recall"] == 1.0
    assert res["macro_f1"] == 1.0


def test_open_set_error_penalties() -> None:
    # 2 known queries (spk1, spk2), 2 unknown queries (spk3, spk4)
    y_true = ["spk1", "spk2", "spk3", "spk4"]
    # spk1 is predicted as spk2 (wrong known -> error)
    # spk2 is predicted as unknown (false reject -> error)
    # spk3 is predicted as spk1 (false accept -> error)
    # spk4 is predicted as unknown (correct unknown -> success)
    y_pred = ["spk2", "unknown", "spk1", "unknown"]
    is_known = [True, True, False, False]
    known_labels = ["spk1", "spk2"]

    res = compute_open_set_metrics(y_true, y_pred, is_known, known_labels)
    # Total correct = 1 (spk4), accuracy = 1/4 = 0.25
    assert res["accuracy"] == 0.25
    # known_correct = 0, known_total = 2 -> known_accuracy = 0.0
    assert res["known_accuracy"] == 0.0
    # unknown_correct = 1, unknown_total = 2 -> unknown_rejection = 0.5
    assert res["unknown_rejection"] == 0.5
    # FAR = 1/2 = 0.5
    assert res["false_accept_rate"] == 0.5
    # FRR = 1/2 = 0.5
    assert res["false_reject_rate"] == 0.5
    # Balanced accuracy = (0 + 0.5) / 2 = 0.25
    assert res["balanced_accuracy"] == 0.25


def test_aggregate_episode_metrics_determinism() -> None:
    episodes = [
        {"accuracy": 0.80, "macro_f1": 0.78},
        {"accuracy": 0.85, "macro_f1": 0.84},
        {"accuracy": 0.90, "macro_f1": 0.89},
        {"accuracy": 0.95, "macro_f1": 0.94},
    ]
    summary1 = aggregate_episode_metrics(episodes, seed=20260924)
    summary2 = aggregate_episode_metrics(episodes, seed=20260924)

    assert summary1 == summary2
    assert summary1["accuracy"]["mean"] == pytest.approx(0.875)
    assert (
        summary1["accuracy"]["ci_lower_95"]
        <= summary1["accuracy"]["mean"]
        <= summary1["accuracy"]["ci_upper_95"]
    )
