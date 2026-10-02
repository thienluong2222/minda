"""VAD evaluation metrics (frame-level and event-level).

Specification: Section 9.2 of docs/PLAN_VIVOS_SYNTHETIC_PIPELINE.md.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from meeting_pipeline.domain.contracts import MeetingRecipe, MeetingSegment


def evaluate_vad(
    predicted_segments: list[MeetingSegment],
    recipe: MeetingRecipe,
    frame_step_sec: float = 0.01,
) -> dict[str, Any]:
    """Evaluate predicted VAD segments against ground truth turns from recipe.

    Metrics:
    - Frame-level: Precision, Recall, F1 (at 10ms resolution).
    - Event-level: Total predicted vs total reference segments.
    """
    duration = recipe.canonical_duration_sec
    total_frames = max(1, math.ceil(duration / frame_step_sec))

    ref_mask = np.zeros(total_frames, dtype=bool)
    pred_mask = np.zeros(total_frames, dtype=bool)

    # Populate reference speech mask
    for turn in recipe.turns:
        s_idx = max(0, int(turn.start_sec / frame_step_sec))
        e_idx = min(total_frames, math.ceil(turn.end_sec / frame_step_sec))
        ref_mask[s_idx:e_idx] = True

    # Populate predicted speech mask
    for seg in predicted_segments:
        s_idx = max(0, int(seg.start_sec / frame_step_sec))
        e_idx = min(total_frames, math.ceil(seg.end_sec / frame_step_sec))
        pred_mask[s_idx:e_idx] = True

    # Compute frame-level confusion
    tp = int(np.sum(ref_mask & pred_mask))
    fp = int(np.sum((~ref_mask) & pred_mask))
    fn = int(np.sum(ref_mask & (~pred_mask)))
    tn = int(np.sum((~ref_mask) & (~pred_mask)))

    precision = float(tp / (tp + fp)) if (tp + fp) > 0 else 0.0
    recall = float(tp / (tp + fn)) if (tp + fn) > 0 else 0.0
    f1 = float(2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    return {
        "frame_precision": precision,
        "frame_recall": recall,
        "frame_f1": f1,
        "tp_frames": tp,
        "fp_frames": fp,
        "fn_frames": fn,
        "tn_frames": tn,
        "total_frames": total_frames,
        "predicted_segment_count": len(predicted_segments),
        "reference_turn_count": len(recipe.turns),
    }
