"""Evaluation metrics for closed-set and open-set speaker identification."""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics import (  # type: ignore[import-untyped]
    confusion_matrix,
    precision_recall_fscore_support,
)


def compute_closed_set_metrics(
    y_true: list[str],
    y_pred: list[str],
    labels: list[str],
) -> dict[str, Any]:
    """Compute closed-set identification metrics."""
    if not y_true:
        raise ValueError("y_true cannot be empty")

    correct = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == p)
    accuracy = float(correct / len(y_true))

    p, r, f1, _ = precision_recall_fscore_support(
        y_true,
        y_pred,
        labels=labels,
        average="macro",
        zero_division=0,
    )

    cm = confusion_matrix(y_true, y_pred, labels=labels).tolist()

    return {
        "accuracy": accuracy,
        "macro_precision": float(p),
        "macro_recall": float(r),
        "macro_f1": float(f1),
        "confusion_matrix": cm,
        "labels": labels,
    }


def compute_open_set_metrics(
    y_true: list[str],
    y_pred: list[str],
    is_known: list[bool],
    known_labels: list[str],
) -> dict[str, Any]:
    """Compute open-set identification metrics with 'unknown' class handling."""
    if not y_true:
        raise ValueError("y_true cannot be empty")

    all_labels = [*known_labels, "unknown"]

    # Overall correctness:
    # Known query is correct if y_pred == y_true
    # Unknown query is correct if y_pred == 'unknown'
    correct_count = 0
    known_correct = 0
    known_total = 0
    unknown_correct = 0
    unknown_total = 0
    false_accepts = 0
    false_rejects = 0

    eval_true: list[str] = []
    eval_pred: list[str] = []

    for t, p, k in zip(y_true, y_pred, is_known, strict=True):
        true_label = t if k else "unknown"
        eval_true.append(true_label)
        eval_pred.append(p)

        if k:
            known_total += 1
            if p == t:
                correct_count += 1
                known_correct += 1
            elif p == "unknown":
                false_rejects += 1
        else:
            unknown_total += 1
            if p == "unknown":
                correct_count += 1
                unknown_correct += 1
            else:
                false_accepts += 1

    overall_accuracy = float(correct_count / len(y_true))
    known_accuracy = float(known_correct / known_total) if known_total > 0 else 0.0
    unknown_rejection = float(unknown_correct / unknown_total) if unknown_total > 0 else 0.0
    balanced_accuracy = float((known_accuracy + unknown_rejection) / 2.0)
    far = float(false_accepts / unknown_total) if unknown_total > 0 else 0.0
    frr = float(false_rejects / known_total) if known_total > 0 else 0.0

    p, r, f1, _ = precision_recall_fscore_support(
        eval_true,
        eval_pred,
        labels=all_labels,
        average="macro",
        zero_division=0,
    )

    cm = confusion_matrix(eval_true, eval_pred, labels=all_labels).tolist()

    return {
        "accuracy": overall_accuracy,
        "macro_precision": float(p),
        "macro_recall": float(r),
        "macro_f1": float(f1),
        "known_accuracy": known_accuracy,
        "unknown_rejection": unknown_rejection,
        "balanced_accuracy": balanced_accuracy,
        "false_accept_rate": far,
        "false_reject_rate": frr,
        "confusion_matrix": cm,
        "labels": all_labels,
    }


def aggregate_episode_metrics(
    episode_records: list[dict[str, Any]],
    metric_keys: tuple[str, ...] = (
        "accuracy",
        "macro_precision",
        "macro_recall",
        "macro_f1",
        "known_accuracy",
        "unknown_rejection",
        "balanced_accuracy",
    ),
    n_bootstraps: int = 1000,
    seed: int = 20260924,
) -> dict[str, dict[str, float]]:
    """Aggregate metric statistics and compute 95% bootstrap CI across episodes."""
    if not episode_records:
        return {}

    rng = np.random.RandomState(seed)
    summary: dict[str, dict[str, float]] = {}

    for key in metric_keys:
        values = [r[key] for r in episode_records if key in r]
        if not values:
            continue
        arr = np.asarray(values, dtype=np.float64)

        mean_val = float(np.mean(arr))
        std_val = float(np.std(arr))
        median_val = float(np.median(arr))

        # Bootstrap 95% CI
        n_vals = len(arr)
        if n_vals > 1:
            boot_means = []
            for _ in range(n_bootstraps):
                sample_idx = rng.randint(0, n_vals, size=n_vals)
                boot_means.append(float(np.mean(arr[sample_idx])))
            ci_lower = float(np.percentile(boot_means, 2.5))
            ci_upper = float(np.percentile(boot_means, 97.5))
        else:
            ci_lower = mean_val
            ci_upper = mean_val

        summary[key] = {
            "mean": mean_val,
            "std": std_val,
            "median": median_val,
            "ci_lower_95": ci_lower,
            "ci_upper_95": ci_upper,
        }

    return summary
