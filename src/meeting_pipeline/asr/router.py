"""Adaptive source routing and pre-ASR acoustic quality evaluation.

Evaluates transcript eligibility before decoding to prioritize high-clarity microphones
and gate out severely degraded or unaligned devices.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

from meeting_pipeline.domain.contracts import SourceHypothesis

logger = logging.getLogger(__name__)


@dataclass
class TranscriptPreQuality:
    """Pre-ASR acoustic quality assessment for a recording device."""

    source_id: str
    duration_sec: float
    speech_rms: float
    local_snr_proxy_db: float
    clipping_ratio: float
    dropout_ratio: float
    speech_coverage: float
    is_eligible: bool
    exclusion_reason: str | None
    pre_score: float
    raw_features: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "duration_sec": round(self.duration_sec, 3),
            "speech_rms": round(self.speech_rms, 5),
            "local_snr_proxy_db": round(self.local_snr_proxy_db, 2),
            "clipping_ratio": round(self.clipping_ratio, 4),
            "dropout_ratio": round(self.dropout_ratio, 4),
            "speech_coverage": round(self.speech_coverage, 3),
            "is_eligible": self.is_eligible,
            "exclusion_reason": self.exclusion_reason,
            "pre_score": round(self.pre_score, 4),
        }


def evaluate_source_pre_quality_for_asr(
    source_id: str,
    turn_waveform: np.ndarray,
    sample_rate: int = 16000,
    full_signal: np.ndarray | None = None,
    turn_start_sec: float = 0.0,
    turn_end_sec: float = 0.0,
    sync_status: str = "synchronized",
    vad_coverage: float = 1.0,
) -> TranscriptPreQuality:
    """Assess whether a source is clean and audible enough for speech recognition."""
    dur = float(len(turn_waveform)) / sample_rate if sample_rate > 0 else 0.0
    raw: dict[str, Any] = {
        "sync_status": sync_status,
        "sample_count": len(turn_waveform),
    }

    if dur < 0.05 or len(turn_waveform) == 0:
        return TranscriptPreQuality(
            source_id=source_id,
            duration_sec=dur,
            speech_rms=0.0,
            local_snr_proxy_db=-20.0,
            clipping_ratio=0.0,
            dropout_ratio=1.0,
            speech_coverage=0.0,
            is_eligible=False,
            exclusion_reason="insufficient_audio",
            pre_score=0.0,
            raw_features=raw,
        )

    # 1. Reject unaligned / sync-failed sources
    if sync_status == "alignment_failed":
        return TranscriptPreQuality(
            source_id=source_id,
            duration_sec=dur,
            speech_rms=0.0,
            local_snr_proxy_db=-20.0,
            clipping_ratio=0.0,
            dropout_ratio=0.0,
            speech_coverage=0.0,
            is_eligible=False,
            exclusion_reason="alignment_failed",
            pre_score=0.0,
            raw_features=raw,
        )

    # 2. Clipping detection
    clipping_ratio = float(np.mean(np.abs(turn_waveform) > 0.99))
    raw["clipping_ratio"] = clipping_ratio

    # 3. Dropout detection
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

    # 5. Local SNR proxy from quietest frames (10th percentile)
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

    # Gating criteria for ASR eligibility
    exclusion_reason: str | None = None
    if speech_rms < 1e-4:
        exclusion_reason = "inaudible_signal"
    elif clipping_ratio > 0.15:
        exclusion_reason = "excessive_clipping"
    elif dropout_ratio > 0.70:
        exclusion_reason = "signal_dropout"
    elif snr_proxy_db < 0.0:
        exclusion_reason = "poor_snr"

    is_eligible = exclusion_reason is None

    # Continuous composite score [0.0, 1.0]
    if is_eligible:
        snr_factor = float(np.clip((snr_proxy_db - 0.0) / 25.0, 0.1, 1.0))
        clean_factor = float(np.clip(1.0 - (clipping_ratio * 4.0 + dropout_ratio * 2.0), 0.1, 1.0))
        cov_factor = float(np.clip(vad_coverage, 0.3, 1.0))
        rms_factor = float(np.clip(speech_rms / 0.15, 0.1, 1.0))

        pre_score = float(
            0.40 * snr_factor + 0.30 * clean_factor + 0.20 * cov_factor + 0.10 * rms_factor
        )
    else:
        pre_score = 0.0

    return TranscriptPreQuality(
        source_id=source_id,
        duration_sec=dur,
        speech_rms=speech_rms,
        local_snr_proxy_db=snr_proxy_db,
        clipping_ratio=clipping_ratio,
        dropout_ratio=dropout_ratio,
        speech_coverage=vad_coverage,
        is_eligible=is_eligible,
        exclusion_reason=exclusion_reason,
        pre_score=pre_score,
        raw_features=raw,
    )


class AdaptiveAsrRouter:
    """Orchestrates source selection for speech recognition."""

    def __init__(self, mode: Literal["adaptive", "all_source"] = "adaptive") -> None:
        self.mode = mode

    def rank_sources(
        self, evaluations: dict[str, TranscriptPreQuality]
    ) -> list[TranscriptPreQuality]:
        """Rank sources by pre_score descending, prioritizing eligible ones."""
        return sorted(
            evaluations.values(),
            key=lambda q: (1 if q.is_eligible else 0, q.pre_score),
            reverse=True,
        )

    def select_initial_sources(
        self,
        ranked: list[TranscriptPreQuality],
    ) -> list[str]:
        """Select initial sources to decode based on current routing mode."""
        if not ranked:
            return []

        if self.mode == "all_source":
            # Schedule all eligible sources (or all sources if none eligible)
            eligible = [q.source_id for q in ranked if q.is_eligible]
            return eligible if eligible else [q.source_id for q in ranked]

        # Adaptive mode: schedule top-1 initially
        return [ranked[0].source_id]

    def should_schedule_top2(
        self,
        top1_hypothesis: SourceHypothesis,
        ranked: list[TranscriptPreQuality],
        delta_threshold: float = 0.05,
    ) -> tuple[bool, str | None]:
        """Determine if the 2nd-best source should also be transcribed."""
        if self.mode == "all_source":
            return False, None

        if len(ranked) < 2:
            return False, None

        top2 = ranked[1]
        if not top2.is_eligible:
            return False, None

        # Reason 1: Top-1 decode failed, empty or rejected as unreliable
        if top1_hypothesis.asr_status != "transcribed":
            return True, f"top1_{top1_hypothesis.asr_status}"

        # Reason 2: Top-1 produced quality warnings (e.g. repeated words or retry)
        quality_warnings = set(top1_hypothesis.asr_warnings) - {
            "asr_boundary_words_recovered",
            "asr_boundary_words_reconciled",
        }
        if quality_warnings:
            return True, "top1_has_warnings"

        # Reason 3: Very narrow quality margin between top-1 and top-2
        margin = ranked[0].pre_score - top2.pre_score
        if margin < delta_threshold:
            return True, f"narrow_quality_margin_{margin:.3f}"

        # Reason 4: Low confidence from model
        mean_conf = top1_hypothesis.asr_features.get("mean_confidence")
        if mean_conf is not None and mean_conf < 0.70:
            return True, f"low_top1_confidence_{mean_conf:.2f}"

        return False, None
