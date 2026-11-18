"""Multi-source speaker identification using cosine similarity and quality weighting.

Specification: Section 10.2 of docs/PLAN_VIVOS_SYNTHETIC_PIPELINE.md.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from meeting_pipeline.speaker.encoder import BaseSpeakerEncoder, create_speaker_encoder

logger = logging.getLogger(__name__)


def identify_multi_source_speaker(
    segment_waveforms: dict[str, np.ndarray[Any, np.dtype[np.float32]]],
    speaker_prototypes: dict[str, np.ndarray[Any, np.dtype[np.float32]]],
    audio_quality_scores: dict[str, float],
    encoder: BaseSpeakerEncoder | None = None,
    fixed_source_id: str | None = None,
    temperature: float = 1.5,
    unknown_threshold: float = 0.35,
) -> dict[str, Any]:
    """Identify speaker for a segment using multiple device waveforms.

    Implements:
    - Fixed source baseline
    - Best audio quality baseline
    - Unweighted mean baseline
    - Quality-weighted multi-source baseline
    """
    if encoder is None:
        encoder = create_speaker_encoder()

    # Extract embeddings for each device
    device_embeddings: dict[str, np.ndarray[Any, np.dtype[np.float32]]] = {}
    for dev_id, wave in segment_waveforms.items():
        if len(wave) < 1600:  # < 0.1s
            continue
        try:
            emb = encoder.encode(wave)
            norm = float(np.linalg.norm(emb))
            if norm > 1e-8:
                emb = emb / norm
            device_embeddings[dev_id] = emb
        except Exception as exc:
            logger.warning("Failed to extract embedding for device %s: %s", dev_id, exc)

    if not device_embeddings or not speaker_prototypes:
        return {
            "predicted_speaker_id": "unknown",
            "confidence": 0.0,
            "baseline_predictions": {},
            "all_speaker_scores": {},
        }

    # Compute cosine similarities for each (device, speaker)
    all_speakers = sorted(speaker_prototypes.keys())
    device_sims: dict[str, dict[str, float]] = {}

    for dev_id, emb in device_embeddings.items():
        device_sims[dev_id] = {}
        for spk_id in all_speakers:
            proto = speaker_prototypes[spk_id]
            sim = float(np.dot(emb, proto))
            device_sims[dev_id][spk_id] = sim

    # 1. Baseline: Fixed source
    f_src = fixed_source_id if fixed_source_id in device_sims else next(iter(device_sims.keys()))
    fixed_scores = device_sims[f_src]
    pred_fixed = max(fixed_scores, key=lambda s: fixed_scores[s])

    # 2. Baseline: Best audio quality source
    best_dev = max(
        device_sims.keys(),
        key=lambda d: audio_quality_scores.get(d, 0.5),
    )
    best_dev_scores = device_sims[best_dev]
    pred_best_quality = max(best_dev_scores, key=lambda s: best_dev_scores[s])

    # 3. Baseline: Unweighted mean
    mean_scores: dict[str, float] = {}
    for spk_id in all_speakers:
        mean_scores[spk_id] = float(np.mean([device_sims[d][spk_id] for d in device_sims]))
    pred_mean = max(mean_scores, key=lambda s: mean_scores[s])

    # 4. Multi-source Quality-Weighted (Section 12.5)
    # w_d = max(epsilon, audio_quality_score_d) ^ temperature
    weighted_scores: dict[str, float] = {}
    weights = {d: max(1e-4, audio_quality_scores.get(d, 0.5)) ** temperature for d in device_sims}
    total_w = sum(weights.values())

    for spk_id in all_speakers:
        w_sum = sum(weights[d] * device_sims[d][spk_id] for d in device_sims)
        weighted_scores[spk_id] = float(w_sum / total_w)

    best_spk = max(weighted_scores, key=lambda s: weighted_scores[s])
    best_conf = weighted_scores[best_spk]

    if best_conf < unknown_threshold:
        final_spk = "unknown"
    else:
        final_spk = best_spk

    return {
        "predicted_speaker_id": final_spk,
        "confidence": round(best_conf, 4),
        "baseline_predictions": {
            "fixed_source": pred_fixed,
            "best_audio_quality": pred_best_quality,
            "unweighted_mean": pred_mean,
            "quality_weighted": best_spk,
        },
        "all_speaker_scores": {s: round(sc, 4) for s, sc in weighted_scores.items()},
    }
