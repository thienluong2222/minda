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
    speech_seconds: float | None
    speech_coverage: float | None
    local_snr_proxy_db: float | None
    clipping_ratio: float | None
    dropout_ratio: float | None
    local_speaker_purity: float | None
    is_eligible: bool
    exclusion_reason: str | None = None
    identity_quality_score: float = 0.0
    identity_weight: float = 0.0
    raw_features: dict[str, Any] = field(default_factory=dict)
    valid_coverage_interval: list[float] | None = None
    sync_status: str | None = None
    local_sync_residual_ms: float | None = None
    supporting_source: bool | None = None
    support_duration_sec: float | None = None
    embedding_status: str = "not_run"
    quality_formula_version: str = "speaker_q_v3"
    candidate_cosine_scores: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "duration_sec": round(self.duration_sec, 3),
            "speech_seconds": round(self.speech_seconds, 3)
            if self.speech_seconds is not None
            else None,
            "speech_coverage": round(self.speech_coverage, 3)
            if self.speech_coverage is not None
            else None,
            "local_snr_proxy_db": round(self.local_snr_proxy_db, 2)
            if self.local_snr_proxy_db is not None
            else None,
            "clipping_ratio": round(self.clipping_ratio, 4)
            if self.clipping_ratio is not None
            else None,
            "dropout_ratio": round(self.dropout_ratio, 4)
            if self.dropout_ratio is not None
            else None,
            "local_speaker_purity": round(self.local_speaker_purity, 3)
            if self.local_speaker_purity is not None
            else None,
            "is_eligible": self.is_eligible,
            "exclusion_reason": self.exclusion_reason,
            "identity_quality_score": round(self.identity_quality_score, 4),
            "identity_weight": round(self.identity_weight, 4),
            "raw_features": self.raw_features,
            "valid_coverage_interval": self.valid_coverage_interval,
            "sync_status": self.sync_status,
            "local_sync_residual_ms": self.local_sync_residual_ms,
            "supporting_source": self.supporting_source,
            "support_duration_sec": self.support_duration_sec,
            "embedding_status": self.embedding_status,
            "quality_formula_version": self.quality_formula_version,
            "candidate_cosine_scores": self.candidate_cosine_scores,
        }


def evaluate_source_quality_for_speaker_id(
    source_id: str,
    turn_waveform: np.ndarray,
    sample_rate: int,
    full_signal: np.ndarray | None = None,
    turn_start_sec: float = 0.0,
    turn_end_sec: float = 0.0,
    sync_status: str | None = None,
    vad_coverage: float | None = None,
    purity: float | None = None,
    valid_coverage_interval: list[float] | None = None,
    local_sync_residual_ms: float | None = None,
    support_duration_sec: float | None = None,
    coverage_fraction: float | None = None,
    residual_gate_ms: float = 20.0,
    purity_gate: float = 0.8,
    ablate_quality_feature: str | None = None,
) -> SourceQualityResult:
    """Measure speech coverage, clipping, dropout, and local SNR proxy for speaker ID."""
    dur = float(len(turn_waveform)) / sample_rate if sample_rate > 0 else 0.0
    raw: dict[str, Any] = {
        "sync_status": sync_status,
        "sample_count": len(turn_waveform),
    }

    missing_reason: str | None = None
    if valid_coverage_interval is None:
        missing_reason = "missing_valid_coverage"
    elif coverage_fraction is not None and coverage_fraction < 0.8:
        missing_reason = "outside_valid_coverage"
    elif sync_status is None:
        missing_reason = "missing_sync_status"
    elif sync_status == "alignment_failed":
        missing_reason = "alignment_failed"
    elif sync_status == "drift_unresolved" and (
        local_sync_residual_ms is None or local_sync_residual_ms > residual_gate_ms
    ):
        missing_reason = "drift_unresolved_without_local_evidence"
    elif local_sync_residual_ms is not None and local_sync_residual_ms > residual_gate_ms:
        missing_reason = "excessive_sync_residual"
    elif vad_coverage is None or purity is None or support_duration_sec is None:
        missing_reason = "missing_source_activity"
    elif support_duration_sec < 0.2:
        missing_reason = "no_source_speech_support"
    elif purity < purity_gate and ablate_quality_feature != "purity":
        missing_reason = "multiple_local_speakers"
    if missing_reason is not None:
        return SourceQualityResult(
            source_id=source_id,
            duration_sec=dur,
            speech_seconds=support_duration_sec,
            speech_coverage=vad_coverage,
            local_snr_proxy_db=None,
            clipping_ratio=None,
            dropout_ratio=None,
            local_speaker_purity=purity,
            is_eligible=False,
            exclusion_reason=missing_reason,
            raw_features=raw,
            valid_coverage_interval=valid_coverage_interval,
            sync_status=sync_status,
            local_sync_residual_ms=local_sync_residual_ms,
            supporting_source=(
                support_duration_sec >= 0.2 if support_duration_sec is not None else None
            ),
            support_duration_sec=support_duration_sec,
        )

    if dur < 0.05 or len(turn_waveform) == 0:
        return SourceQualityResult(
            source_id=source_id,
            duration_sec=dur,
            speech_seconds=0.0,
            speech_coverage=0.0,
            local_snr_proxy_db=None,
            clipping_ratio=None,
            dropout_ratio=None,
            local_speaker_purity=purity,
            is_eligible=False,
            exclusion_reason="insufficient_audio",
            identity_quality_score=0.0,
            raw_features=raw,
            valid_coverage_interval=valid_coverage_interval,
            sync_status=sync_status,
            local_sync_residual_ms=local_sync_residual_ms,
            supporting_source=True,
            support_duration_sec=support_duration_sec,
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

    assert vad_coverage is not None and purity is not None
    # The clip has already been selected from speech-active frames. Multiplying
    # by whole-turn coverage again would double-discount short supported clips.
    assert support_duration_sec is not None
    speech_sec = min(dur, support_duration_sec)
    raw["speech_seconds"] = speech_sec

    # Gating criteria for speaker identification eligibility
    exclusion_reason: str | None = None
    if dur < 0.25 or speech_sec < 0.20:
        exclusion_reason = "insufficient_speech"
    elif clipping_ratio > 0.08 and ablate_quality_feature != "clipping":
        exclusion_reason = "excessive_clipping"
    elif dropout_ratio > 0.25 and ablate_quality_feature != "dropout":
        exclusion_reason = "signal_dropout"
    elif snr_proxy_db < 2.0 and ablate_quality_feature != "snr":
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
        effective_clipping = 0.0 if ablate_quality_feature == "clipping" else clipping_ratio
        effective_dropout = 0.0 if ablate_quality_feature == "dropout" else dropout_ratio
        clean_factor = float(
            np.clip(1.0 - (effective_clipping * 5.0 + effective_dropout * 2.0), 0.1, 1.0)
        )
        purity_factor = float(np.clip(purity, 0.5, 1.0))
        factors = {
            "snr": (0.40, snr_factor),
            "duration": (0.30, dur_factor),
            "clean": (0.20, clean_factor),
            "purity": (0.10, purity_factor),
        }
        factors.pop(ablate_quality_feature or "", None)
        quality_score = float(
            sum(weight * value for weight, value in factors.values())
            / sum(weight for weight, _ in factors.values())
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
        valid_coverage_interval=valid_coverage_interval,
        sync_status=sync_status,
        local_sync_residual_ms=local_sync_residual_ms,
        supporting_source=True,
        support_duration_sec=support_duration_sec,
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
