"""Segment-level PhoWhisper ASR, adaptive routing and quality scoring across sources.

Specification: Section 7 of docs/PLAN_VAD_SPEAKER_ASR_MULTI_SOURCE_2026-10-03.md.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

import numpy as np

from meeting_pipeline.adapters.phowhisper_asr import AsrResult, BaseAsrAdapter
from meeting_pipeline.asr.cache import AsrCache, compute_asr_cache_key
from meeting_pipeline.asr.quality import check_asr_quality
from meeting_pipeline.asr.router import (
    AdaptiveAsrRouter,
    TranscriptPreQuality,
    evaluate_source_pre_quality_for_asr,
)
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
    """Transcribe a meeting segment across all recording devices (legacy direct interface)."""
    hypotheses: dict[str, SourceHypothesis] = {}
    asr_config = (
        quality_config
        or getattr(asr_adapter, "config", None)
        or AsrConfig(model_id="fake", model_revision="test")
    )

    for dev_id, wave in segment_waveforms.items():
        audio_feats = extract_acoustic_features(wave, sample_rate=sample_rate)
        audio_q_score = compute_audio_quality_score(audio_feats)

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
                normalize_vietnamese_text(asr_res.text) if asr_status == "transcribed" else ""
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
                            round(float(tw.confidence), 3) if tw.confidence is not None else None
                        ),
                    )
                )

            measured_confidences = [w.asr_confidence for w in words if w.asr_confidence is not None]
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
                "mean_confidence": (round(mean_asr_conf, 3) if mean_asr_conf is not None else None),
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


def transcribe_turn_adaptive(
    meeting_id: str,
    turn_id: str,
    core_start_sec: float,
    core_end_sec: float,
    aligned_signals: dict[str, np.ndarray],
    sync_metadata: dict[str, Any],
    asr_adapter: BaseAsrAdapter,
    asr_config: AsrConfig,
    sample_rate: int = 16000,
    prev_boundary_sec: float | None = None,
    next_boundary_sec: float | None = None,
    cache: AsrCache | None = None,
) -> tuple[dict[str, SourceHypothesis], dict[str, Any]]:
    """Transcribe a speech turn with context windowing, adaptive routing and midpoint filtering."""
    context_sec = float(asr_config.chunk_context_seconds)
    clip_start_sec = max(0.0, core_start_sec - context_sec)
    if prev_boundary_sec is not None and prev_boundary_sec > clip_start_sec:
        clip_start_sec = max(prev_boundary_sec, clip_start_sec)

    max_meeting_sec = max(len(sig) for sig in aligned_signals.values()) / sample_rate
    clip_end_sec = min(max_meeting_sec, core_end_sec + context_sec)
    if next_boundary_sec is not None and next_boundary_sec < clip_end_sec:
        clip_end_sec = min(next_boundary_sec, clip_end_sec)

    # 1. Pre-ASR acoustic quality evaluation across all sources
    pre_qualities: dict[str, TranscriptPreQuality] = {}
    sliced_clips: dict[str, np.ndarray] = {}

    for src_id, full_sig in aligned_signals.items():
        s_idx = max(0, int(clip_start_sec * sample_rate))
        e_idx = min(len(full_sig), int(clip_end_sec * sample_rate))
        clip = full_sig[s_idx:e_idx] if e_idx > s_idx else np.zeros(0, dtype=np.float32)
        sliced_clips[src_id] = clip

        sync_status = sync_metadata.get(src_id, {}).get("status", "synchronized")
        pre_qual = evaluate_source_pre_quality_for_asr(
            source_id=src_id,
            turn_waveform=clip,
            sample_rate=sample_rate,
            full_signal=full_sig,
            turn_start_sec=core_start_sec,
            turn_end_sec=core_end_sec,
            sync_status=sync_status,
        )
        pre_qualities[src_id] = pre_qual

    router = AdaptiveAsrRouter(mode=asr_config.routing_mode)
    ranked = router.rank_sources(pre_qualities)
    initial_sources = router.select_initial_sources(ranked)

    scheduled_sources: list[str] = list(initial_sources)
    routing_reasons: dict[str, str] = {src: "scheduled_initial" for src in scheduled_sources}

    hypotheses: dict[str, SourceHypothesis] = {}

    def _decode_source(source_id: str, reason: str) -> SourceHypothesis:
        clip = sliced_clips[source_id]
        dur = len(clip) / sample_rate
        audio_feats = extract_acoustic_features(clip, sample_rate=sample_rate)
        audio_q_score = compute_audio_quality_score(audio_feats)

        if dur < 0.05 or np.max(np.abs(clip), initial=0.0) < 1e-6:
            return SourceHypothesis(
                meeting_id=meeting_id,
                segment_id=turn_id,
                source_id=source_id,
                text="",
                words=[],
                audio_features=audio_feats,
                asr_features={"mean_confidence": None, "word_agreement": None},
                asr_status="empty",
                asr_warnings=["empty_audio"],
                raw_asr_candidates=[],
                audio_quality_score=round(audio_q_score, 4),
                transcript_quality_score=0.0,
                routing_reason=reason,
            )

        cache_key = compute_asr_cache_key(
            waveform=clip,
            sample_rate=sample_rate,
            model_id=asr_config.model_id,
            model_revision=asr_config.model_revision,
        )

        asr_res: AsrResult | None = None
        if cache is not None:
            asr_res = cache.get(cache_key)

        if asr_res is None:
            try:
                asr_res = asr_adapter.transcribe(clip, sample_rate=sample_rate)
                if cache is not None:
                    cache.put(cache_key, asr_res)
            except Exception as exc:
                logger.warning("ASR failed for turn %s source %s: %s", turn_id, source_id, exc)
                asr_res = AsrResult(
                    text="",
                    words=[],
                    status="failed",
                    warnings=[f"asr_exception: {exc}"],
                    raw_candidates=[],
                )

        asr_status = asr_res.status
        asr_warnings = list(asr_res.warnings)
        raw_candidates = list(asr_res.raw_candidates)

        # Midpoint ownership filtering: token belongs to core only if midpoint is inside core
        words: list[WordHypothesis] = []
        if asr_status == "transcribed":
            for tw in asr_res.words:
                raw_w = getattr(tw, "text", getattr(tw, "word", ""))
                w_norm = normalize_vietnamese_text(raw_w)
                if not w_norm:
                    continue

                abs_start = round(clip_start_sec + tw.start_sec, 3)
                abs_end = round(clip_start_sec + tw.end_sec, 3)
                midpoint = (abs_start + abs_end) / 2.0

                # Midpoint invariant check
                if (core_start_sec - 1e-4) <= midpoint <= (core_end_sec + 1e-4):
                    # Flag boundary words or words with degenerate timing as uncertain
                    is_near_boundary = (
                        abs(abs_start - core_start_sec) < 0.05
                        or abs(abs_end - core_end_sec) < 0.05
                        or abs_end <= abs_start
                    )
                    time_status: Literal["exact", "uncertain"] = (
                        "uncertain" if is_near_boundary else "exact"
                    )
                    words.append(
                        WordHypothesis(
                            word=w_norm,
                            start_sec=abs_start,
                            end_sec=max(abs_start + 0.01, abs_end),
                            asr_confidence=(
                                round(float(tw.confidence), 3)
                                if tw.confidence is not None
                                else None
                            ),
                            time_status=time_status,
                        )
                    )

        # Re-derive core text from kept midpoint words
        core_text = " ".join(w.word for w in words).strip() if asr_status == "transcribed" else ""

        measured_confs = [w.asr_confidence for w in words if w.asr_confidence is not None]
        mean_asr_conf = float(np.mean(measured_confs)) if measured_confs else None

        transcript_q_score = (
            compute_transcript_quality_score(
                audio_quality_score=audio_q_score,
                asr_confidence=mean_asr_conf if mean_asr_conf is not None else 0.5,
                word_agreement=0.5,
            )
            if asr_status == "transcribed"
            else 0.0
        )

        return SourceHypothesis(
            meeting_id=meeting_id,
            segment_id=turn_id,
            source_id=source_id,
            text=core_text,
            words=words,
            audio_features=audio_feats,
            asr_features={
                "mean_confidence": round(mean_asr_conf, 3) if mean_asr_conf is not None else None,
                "word_agreement": None,
                "fusion_confidence_heuristic": 0.5,
            },
            asr_status=asr_status,
            asr_warnings=list(dict.fromkeys(asr_warnings)),
            raw_asr_candidates=raw_candidates,
            audio_quality_score=round(audio_q_score, 4),
            transcript_quality_score=round(transcript_q_score, 4),
            routing_reason=reason,
        )

    # Decode initial scheduled sources
    for src_id in scheduled_sources:
        hypotheses[src_id] = _decode_source(src_id, routing_reasons[src_id])

    # In adaptive mode, check if top-2 should be scheduled
    if asr_config.routing_mode == "adaptive" and len(ranked) >= 2:
        top1_id = scheduled_sources[0]
        top1_hyp = hypotheses[top1_id]
        need_top2, trigger_reason = router.should_schedule_top2(
            top1_hypothesis=top1_hyp,
            ranked=ranked,
            delta_threshold=asr_config.adaptive_delta_threshold,
        )
        if need_top2:
            top2_id = ranked[1].source_id
            scheduled_sources.append(top2_id)
            reason_msg = f"scheduled_fallback_{trigger_reason}"
            routing_reasons[top2_id] = reason_msg
            hypotheses[top2_id] = _decode_source(top2_id, reason_msg)

    # For unscheduled sources, assign explicit "not_run" hypothesis
    unscheduled = [src for src in aligned_signals if src not in scheduled_sources]
    for unscheduled_id in unscheduled:
        pre = pre_qualities.get(unscheduled_id)
        pre_audio_score = pre.pre_score if pre else 0.0
        hypotheses[unscheduled_id] = SourceHypothesis(
            meeting_id=meeting_id,
            segment_id=turn_id,
            source_id=unscheduled_id,
            text="",
            words=[],
            audio_features={},
            asr_features={"mean_confidence": None, "word_agreement": None},
            asr_status="not_run",
            asr_warnings=[],
            raw_asr_candidates=[],
            audio_quality_score=round(pre_audio_score, 4),
            transcript_quality_score=0.0,
            routing_reason="gated_out_by_adaptive_routing",
        )

    routing_metadata = {
        "turn_id": turn_id,
        "core_interval": [round(core_start_sec, 3), round(core_end_sec, 3)],
        "clip_interval": [round(clip_start_sec, 3), round(clip_end_sec, 3)],
        "routing_mode": asr_config.routing_mode,
        "scheduled_sources": scheduled_sources,
        "abstained_sources": unscheduled,
        "ranked_pre_qualities": [q.as_dict() for q in ranked],
    }

    return hypotheses, routing_metadata
