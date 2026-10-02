"""Source quality assessment and multi-source evidence fusion for speaker identification.

Specification: Section 6 (WP3) of docs/PLAN_VAD_SPEAKER_ASR_MULTI_SOURCE_2026-10-03.md.
Separates speaker identity quality from VAD and ASR transcript quality.
Provides quality gating, SNR proxy contrast, clipping/dropout checks, and 4 fusion policies:
- P0_FIXED_REFERENCE: Reference source only
- P1_TOP1_QUALITY: Best eligible quality source
- P2_EMBEDDING_FUSION: Quality-gated weighted average embedding
- P3_WEIGHTED_SCORE_FUSION: Quality-gated candidate score averaging
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, cast

import numpy as np

logger = logging.getLogger(__name__)


class SpeakerFusionPolicy(StrEnum):
    """Multi-source evidence combination policy for speaker identification."""

    P0_FIXED_REFERENCE = "P0_FIXED_REFERENCE"
    P1_TOP1_QUALITY = "P1_TOP1_QUALITY"
    P2_EMBEDDING_FUSION = "P2_EMBEDDING_FUSION"
    P3_WEIGHTED_SCORE_FUSION = "P3_WEIGHTED_SCORE_FUSION"


@dataclass(slots=True)
class SourceQualityResult:
    """Detailed quality evaluation of a single audio source for speaker identification."""

    source_id: str
    duration_sec: float
    speech_seconds: float
    speech_coverage: float
    local_snr_proxy_db: float
    clipping_ratio: float
    dropout_ratio: float
    local_speaker_purity: float
    is_eligible: bool
    exclusion_reason: str | None = None
    identity_quality_score: float = 0.0
    identity_weight: float = 0.0
    raw_features: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "duration_sec": round(self.duration_sec, 3),
            "speech_seconds": round(self.speech_seconds, 3),
            "speech_coverage": round(self.speech_coverage, 3),
            "local_snr_proxy_db": round(self.local_snr_proxy_db, 2),
            "clipping_ratio": round(self.clipping_ratio, 4),
            "dropout_ratio": round(self.dropout_ratio, 4),
            "local_speaker_purity": round(self.local_speaker_purity, 3),
            "is_eligible": self.is_eligible,
            "exclusion_reason": self.exclusion_reason,
            "identity_quality_score": round(self.identity_quality_score, 4),
            "identity_weight": round(self.identity_weight, 4),
            "raw_features": self.raw_features,
        }


def evaluate_source_quality_for_speaker_id(
    source_id: str,
    turn_waveform: np.ndarray,
    sample_rate: int,
    full_signal: np.ndarray | None = None,
    turn_start_sec: float = 0.0,
    turn_end_sec: float = 0.0,
    sync_status: str = "synchronized",
    vad_coverage: float = 1.0,
    purity: float = 1.0,
) -> SourceQualityResult:
    """Measure speech coverage, clipping, dropout, and local SNR proxy for speaker ID."""
    dur = float(len(turn_waveform)) / sample_rate if sample_rate > 0 else 0.0
    raw: dict[str, Any] = {
        "sync_status": sync_status,
        "sample_count": len(turn_waveform),
    }

    if dur < 0.05 or len(turn_waveform) == 0:
        return SourceQualityResult(
            source_id=source_id,
            duration_sec=dur,
            speech_seconds=0.0,
            speech_coverage=0.0,
            local_snr_proxy_db=-20.0,
            clipping_ratio=0.0,
            dropout_ratio=1.0,
            local_speaker_purity=purity,
            is_eligible=False,
            exclusion_reason="insufficient_audio",
            identity_quality_score=0.0,
            raw_features=raw,
        )

    # 1. Sync validation check
    if sync_status == "alignment_failed":
        return SourceQualityResult(
            source_id=source_id,
            duration_sec=dur,
            speech_seconds=0.0,
            speech_coverage=0.0,
            local_snr_proxy_db=-20.0,
            clipping_ratio=0.0,
            dropout_ratio=0.0,
            local_speaker_purity=purity,
            is_eligible=False,
            exclusion_reason="alignment_failed",
            identity_quality_score=0.0,
            raw_features=raw,
        )

    # 2. Clipping detection: samples exceeding 0.99
    clipping_ratio = float(np.mean(np.abs(turn_waveform) > 0.99))
    raw["clipping_ratio"] = clipping_ratio

    # 3. True dropout detection: continuous blocks with RMS < 1e-6
    frame_sz = int(0.020 * sample_rate)
    hop_sz = int(0.010 * sample_rate)
    frames = [
        turn_waveform[i : i + frame_sz] for i in range(0, len(turn_waveform) - frame_sz + 1, hop_sz)
    ]
    if frames:
        f_energies = np.array([float(np.sqrt(np.mean(f**2))) for f in frames])
        dropout_ratio = float(np.mean(f_energies < 1e-6))
    else:
        dropout_ratio = 0.0
    raw["dropout_ratio"] = dropout_ratio

    # 4. Turn speech RMS
    speech_rms = float(np.sqrt(np.mean(turn_waveform.astype(np.float64) ** 2)))
    raw["speech_rms"] = speech_rms

    # 5. Local background noise contrast (SNR proxy) on same device
    # Estimate noise floor from quietest frames (10th percentile) around turn or full signal
    bg_rms = 1e-4
    if full_signal is not None and len(full_signal) >= frame_sz:
        s_win = max(0, int((turn_start_sec - 1.5) * sample_rate))
        e_win = min(len(full_signal), int((turn_end_sec + 1.5) * sample_rate))
        local_clip = full_signal[s_win:e_win]
        if len(local_clip) >= frame_sz:
            l_frames = [
                local_clip[i : i + frame_sz]
                for i in range(0, len(local_clip) - frame_sz + 1, hop_sz)
            ]
            if l_frames:
                l_rms = np.array(
                    [float(np.sqrt(np.mean(f.astype(np.float64) ** 2))) for f in l_frames]
                )
                bg_rms = max(1e-5, float(np.percentile(l_rms, 10)))
    elif len(turn_waveform) >= frame_sz:
        f_rms = np.array([float(np.sqrt(np.mean(f.astype(np.float64) ** 2))) for f in frames])
        if len(f_rms) > 0:
            bg_rms = max(1e-5, float(np.percentile(f_rms, 10)))

    snr_proxy_db = float(20.0 * np.log10(max(speech_rms, 1e-6) / max(bg_rms, 1e-6)))
    raw["local_snr_proxy_db"] = snr_proxy_db

    speech_sec = dur * max(0.0, min(1.0, vad_coverage))
    raw["speech_seconds"] = speech_sec

    # Gating criteria for speaker identification eligibility
    exclusion_reason: str | None = None
    if dur < 0.25 or speech_sec < 0.20:
        exclusion_reason = "insufficient_speech"
    elif clipping_ratio > 0.08:
        exclusion_reason = "excessive_clipping"
    elif dropout_ratio > 0.25:
        exclusion_reason = "signal_dropout"
    elif snr_proxy_db < 2.0:
        exclusion_reason = "poor_snr"
    elif speech_rms < 1e-4:
        exclusion_reason = "inaudible_signal"

    is_eligible = exclusion_reason is None

    # Compute continuous composite quality score [0.0, 1.0]
    if is_eligible:
        # Logistic / bounded SNR factor: 3dB -> 0.2, 15dB -> 0.8, 25dB+ -> 1.0
        snr_factor = float(np.clip((snr_proxy_db - 2.0) / 20.0, 0.05, 1.0))
        # Duration factor: 0.2s -> 0.2, 1.5s+ -> 1.0
        dur_factor = float(np.clip(speech_sec / 1.5, 0.2, 1.0))
        clean_factor = float(np.clip(1.0 - (clipping_ratio * 5.0 + dropout_ratio * 2.0), 0.1, 1.0))
        purity_factor = float(np.clip(purity, 0.5, 1.0))

        quality_score = float(
            0.40 * snr_factor + 0.30 * dur_factor + 0.20 * clean_factor + 0.10 * purity_factor
        )
    else:
        quality_score = 0.0

    return SourceQualityResult(
        source_id=source_id,
        duration_sec=dur,
        speech_seconds=speech_sec,
        speech_coverage=vad_coverage,
        local_snr_proxy_db=snr_proxy_db,
        clipping_ratio=clipping_ratio,
        dropout_ratio=dropout_ratio,
        local_speaker_purity=purity,
        is_eligible=is_eligible,
        exclusion_reason=exclusion_reason,
        identity_quality_score=quality_score,
        identity_weight=0.0,  # Computed across sources in session
        raw_features=raw,
    )


def compute_normalized_source_weights(
    evaluations: dict[str, SourceQualityResult],
    temperature: float = 1.0,
) -> dict[str, float]:
    """Compute normalized positive weights across eligible sources using quality scores."""
    eligible = {
        sid: res
        for sid, res in evaluations.items()
        if res.is_eligible and res.identity_quality_score > 0
    }
    if not eligible:
        # Fallback: if all failed, pick the best among inaudible/poor_snr if any
        if evaluations:
            best_sid = max(evaluations, key=lambda sid: evaluations[sid].identity_quality_score)
            return {best_sid: 1.0}
        return {}

    scores = np.array([res.identity_quality_score for res in eligible.values()], dtype=np.float32)
    # Scale with temperature
    if temperature != 1.0 and temperature > 0:
        scores = scores ** (1.0 / temperature)

    total = float(np.sum(scores))
    if total <= 1e-8:
        equal_w = 1.0 / len(eligible)
        return {sid: equal_w for sid in eligible}

    weights = scores / total
    return {sid: float(weights[i]) for i, sid in enumerate(eligible)}


def fuse_turn_speaker_embeddings(
    embeddings_by_source: dict[str, np.ndarray],
    weights: dict[str, float],
) -> np.ndarray | None:
    """Perform P2 weighted embedding fusion with L2 normalization."""
    valid_items = [
        (embeddings_by_source[sid], weights[sid])
        for sid in embeddings_by_source
        if sid in weights and weights[sid] > 0
    ]
    if not valid_items:
        return None

    vectors = np.stack([v for v, _ in valid_items])
    w = np.array([weight for _, weight in valid_items], dtype=np.float32)
    w /= np.sum(w)

    fused = np.sum(vectors * w[:, np.newaxis], axis=0)
    norm = float(np.linalg.norm(fused))
    if norm > 1e-8:
        fused /= norm
    return cast(np.ndarray, fused.astype(np.float32))


def fuse_turn_candidate_scores(
    candidate_scores_by_source: dict[str, dict[str, float]],
    weights: dict[str, float],
) -> dict[str, float]:
    """Perform P3 quality-gated weighted score fusion across candidates."""
    combined: dict[str, float] = {}
    valid_sources = [
        sid for sid in candidate_scores_by_source if sid in weights and weights[sid] > 0
    ]
    if not valid_sources:
        return {}

    total_w = sum(weights[sid] for sid in valid_sources)
    if total_w <= 1e-8:
        return {}

    for sid in valid_sources:
        w = weights[sid] / total_w
        for candidate_id, score in candidate_scores_by_source[sid].items():
            combined[candidate_id] = combined.get(candidate_id, 0.0) + (score * w)

    return combined
