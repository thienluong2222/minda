"""Explainable multi-source identity and ASR-source weighting."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class CandidateEvidence:
    """Quality features and per-speaker cosine scores for one source candidate."""

    source_id: str
    eligible: bool
    speech_presence: float | None
    speech_noise_contrast: float | None
    clipping_avoidance: float | None
    speaker_scores: dict[str, float]


def quality_score(evidence: CandidateEvidence, coefficients: tuple[float, float, float]) -> float:
    """Combine available [0, 1] features, renormalizing missing coefficients."""
    features = (
        evidence.speech_presence,
        evidence.speech_noise_contrast,
        evidence.clipping_avoidance,
    )
    available = [
        (value, weight)
        for value, weight in zip(features, coefficients, strict=True)
        if value is not None
    ]
    if not available:
        raise ValueError("At least one quality feature is required")
    denominator = sum(weight for _, weight in available)
    return sum(float(value) * weight for value, weight in available) / denominator


def identity_weights(
    candidates: list[CandidateEvidence],
    coefficients: tuple[float, float, float] = (0.4, 0.4, 0.2),
    temperature: float = 0.25,
) -> dict[str, float]:
    """Compute alpha weights only across eligible candidates with quality evidence."""
    if temperature <= 0:
        raise ValueError("temperature must be positive")
    eligible = [candidate for candidate in candidates if candidate.eligible]
    if not eligible:
        return {candidate.source_id: 0.0 for candidate in candidates}
    scores = np.asarray([quality_score(candidate, coefficients) for candidate in eligible])
    logits = (scores - np.max(scores)) / temperature
    normalized = np.exp(logits) / np.sum(np.exp(logits))
    result = {candidate.source_id: 0.0 for candidate in candidates}
    result.update(
        {
            candidate.source_id: float(weight)
            for candidate, weight in zip(eligible, normalized, strict=True)
        }
    )
    return result


def fused_identity_scores(
    candidates: list[CandidateEvidence], weights: dict[str, float]
) -> dict[str, float]:
    """Fuse cosine scores with alpha; missing speaker scores do not become zero votes."""
    speaker_ids = {speaker for candidate in candidates for speaker in candidate.speaker_scores}
    fused: dict[str, float] = {}
    for speaker_id in speaker_ids:
        present = [candidate for candidate in candidates if speaker_id in candidate.speaker_scores]
        denominator = sum(weights.get(candidate.source_id, 0) for candidate in present)
        if denominator > 0:
            fused[speaker_id] = (
                sum(
                    weights[candidate.source_id] * candidate.speaker_scores[speaker_id]
                    for candidate in present
                )
                / denominator
            )
    return fused


def selection_weights(
    candidates: list[CandidateEvidence],
    alpha: dict[str, float],
    selected_speaker_id: str | None,
    candidate_match_floor: float,
) -> dict[str, float]:
    """Compute beta after identity selection; unknown tracks use quality alpha."""
    if selected_speaker_id is None:
        return {
            candidate.source_id: alpha.get(candidate.source_id, 0.0) for candidate in candidates
        }
    raw: dict[str, float] = {}
    for candidate in candidates:
        score = candidate.speaker_scores.get(selected_speaker_id)
        if not candidate.eligible or score is None:
            raw[candidate.source_id] = 0.0
            continue
        match = np.clip((score - candidate_match_floor) / (1 - candidate_match_floor), 0, 1)
        raw[candidate.source_id] = alpha.get(candidate.source_id, 0.0) * float(match)
    total = sum(raw.values())
    return raw if total == 0 else {source_id: value / total for source_id, value in raw.items()}
