"""Synchronization evaluation metrics.

Specification: Section 8.3 of docs/PLAN_VIVOS_SYNTHETIC_PIPELINE.md.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from meeting_pipeline.domain.contracts import MeetingRecipe


def evaluate_synchronization(
    predicted_sync: dict[str, dict[str, float]],
    recipe: MeetingRecipe,
) -> dict[str, Any]:
    """Evaluate predicted offset and drift against recipe ground truth.

    Metrics:
    - Offset MAE, median, p95 (in milliseconds).
    - Drift MAE (in ppm).
    - Per-device errors.
    """
    offset_errors_ms: list[float] = []
    drift_errors_ppm: list[float] = []
    per_device_details: dict[str, dict[str, float]] = {}

    for dev_id, dev_cfg in recipe.devices.items():
        if dev_id not in predicted_sync:
            continue

        true_offset = dev_cfg.offset_sec
        true_drift = dev_cfg.drift_ppm

        pred = predicted_sync[dev_id]
        pred_offset = pred.get("offset_sec", 0.0)
        pred_drift = pred.get("drift_ppm", 0.0)

        # Note: relative offset error is calculated against reference
        offset_err_ms = abs(pred_offset - true_offset) * 1000.0
        drift_err_ppm = abs(pred_drift - true_drift)

        offset_errors_ms.append(offset_err_ms)
        drift_errors_ppm.append(drift_err_ppm)

        per_device_details[dev_id] = {
            "true_offset_sec": true_offset,
            "pred_offset_sec": pred_offset,
            "offset_error_ms": offset_err_ms,
            "true_drift_ppm": true_drift,
            "pred_drift_ppm": pred_drift,
            "drift_error_ppm": drift_err_ppm,
        }

    if not offset_errors_ms:
        return {
            "offset_mae_ms": 0.0,
            "offset_median_ms": 0.0,
            "offset_p95_ms": 0.0,
            "drift_mae_ppm": 0.0,
            "devices_evaluated": 0,
            "per_device": {},
        }

    offset_arr = np.array(offset_errors_ms)
    return {
        "offset_mae_ms": float(np.mean(offset_arr)),
        "offset_median_ms": float(np.median(offset_arr)),
        "offset_p95_ms": float(np.percentile(offset_arr, 95)),
        "drift_mae_ppm": float(np.mean(drift_errors_ppm)),
        "devices_evaluated": len(offset_errors_ms),
        "per_device": per_device_details,
    }
