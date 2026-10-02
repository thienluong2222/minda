"""Segment-level PhoWhisper ASR and quality scoring across sources.

Specification: Section 11 of docs/PLAN_VIVOS_SYNTHETIC_PIPELINE.md.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

import numpy as np

from meeting_pipeline.adapters.phowhisper_asr import BaseAsrAdapter
from meeting_pipeline.asr.quality import check_asr_quality
from meeting_pipeline.config import AsrConfig
from meeting_pipeline.data.vivos import normalize_vietnamese_text
from meeting_pipeline.domain.contracts import MeetingSegment, SourceHypothesis, WordHypothesis
from meeting_pipeline.domain.errors import ModelUnavailableError
from meeting_pipeline.fusion.features import (
    compute_audio_quality_score,
    compute_transcript_quality_score,
    extract_acoustic_features,
)

logger = logging.getLogger(__name__)


def transcribe_segment_sources(
    meeting_id: str,
    segment: MeetingSegment,
    segment_waveforms: dict[str, np.ndarray[Any, np.dtype[np.float32]]],
    asr_adapter: BaseAsrAdapter,
    sample_rate: int = 16000,
    quality_config: AsrConfig | None = None,
) -> dict[str, SourceHypothesis]:
    """Transcribe a meeting segment across all recording devices."""
    hypotheses: dict[str, SourceHypothesis] = {}
    asr_config = quality_config or getattr(asr_adapter, "config", None) or AsrConfig(
        model_id="fake", model_revision="test"
    )

    for dev_id, wave in segment_waveforms.items():
        # 1. Acoustic features
        audio_feats = extract_acoustic_features(wave, sample_rate=sample_rate)
        audio_q_score = compute_audio_quality_score(audio_feats)

        # 2. Decode and reject impossible output before it can enter fusion.
        asr_status: Literal["transcribed", "empty", "failed", "unreliable"] = "failed"
        asr_warnings: list[str] = []
        raw_candidates: list[dict[str, Any]] = []
        mean_asr_conf: float | None = None
        try:
            asr_res = asr_adapter.transcribe(wave, sample_rate=sample_rate)
            asr_status = asr_res.status
            asr_warnings = list(asr_res.warnings)
            raw_candidates = list(asr_res.raw_candidates)
            if asr_status == "transcribed":
                quality = check_asr_quality(
                    asr_res.text,
                    asr_res.words,
                    len(wave) / sample_rate,
                    asr_config,
                )
                if not quality.accepted:
                    asr_status = "unreliable"
                    asr_warnings.extend(quality.issues)
                    if not raw_candidates:
                        raw_candidates.append(
                            {
                                "text": asr_res.text,
                                "words": [word.model_dump() for word in asr_res.words],
                                "quality": {"issues": list(quality.issues)},
                            }
                        )

            norm_text = (
                normalize_vietnamese_text(asr_res.text)
                if asr_status == "transcribed"
                else ""
            )

            words: list[WordHypothesis] = []
            for tw in asr_res.words if asr_status == "transcribed" else []:
                raw_w = getattr(tw, "text", getattr(tw, "word", ""))
                w_norm = normalize_vietnamese_text(raw_w)
                if not w_norm:
                    continue
                w_start = round(segment.start_sec + tw.start_sec, 3)
                w_end = round(segment.start_sec + tw.end_sec, 3)
                words.append(
                    WordHypothesis(
                        word=w_norm,
                        start_sec=w_start,
                        end_sec=w_end,
                        asr_confidence=(
                            round(float(tw.confidence), 3)
                            if tw.confidence is not None
                            else None
                        ),
                    )
                )

            measured_confidences = [
                w.asr_confidence for w in words if w.asr_confidence is not None
            ]
            if measured_confidences:
                mean_asr_conf = float(np.mean(measured_confidences))

        except ModelUnavailableError:
            raise
        except Exception as exc:
            logger.warning(
                "ASR transcription failed for %s on device %s: %s",
                segment.segment_id,
                dev_id,
                exc,
            )
            norm_text = ""
            words = []
            asr_status = "failed"
            asr_warnings.append(f"asr_exception: {exc}")

        # Missing model probabilities remain null. The score below is a ranking
        # heuristic for fusion only and must not be shown as ASR confidence.
        transcript_q_score = (
            compute_transcript_quality_score(
                audio_quality_score=audio_q_score,
                asr_confidence=mean_asr_conf if mean_asr_conf is not None else 0.5,
                word_agreement=0.5,
            )
            if asr_status == "transcribed"
            else 0.0
        )

        hypotheses[dev_id] = SourceHypothesis(
            meeting_id=meeting_id,
            segment_id=segment.segment_id,
            source_id=dev_id,
            text=norm_text,
            words=words,
            audio_features=audio_feats,
            asr_features={
                "mean_confidence": (
                    round(mean_asr_conf, 3) if mean_asr_conf is not None else None
                ),
                "word_agreement": None,
                "fusion_confidence_heuristic": 0.5,
            },
            asr_status=asr_status,
            asr_warnings=list(dict.fromkeys(asr_warnings)),
            raw_asr_candidates=raw_candidates,
            audio_quality_score=round(audio_q_score, 4),
            transcript_quality_score=round(transcript_q_score, 4),
        )

    return hypotheses
