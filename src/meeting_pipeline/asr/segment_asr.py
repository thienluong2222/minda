"""Segment-level PhoWhisper ASR, adaptive routing and quality scoring across sources.

Specification: Section 7 of docs/PLAN_VAD_SPEAKER_ASR_MULTI_SOURCE_2026-10-03.md.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any, Literal

import numpy as np
import soundfile as sf

from meeting_pipeline.adapters.phowhisper_asr import AsrResult, BaseAsrAdapter
from meeting_pipeline.asr.boundary_words import (
    BOUNDARY_POLICY_VERSION,
    filter_boundary_words,
    refresh_boundary_hypothesis,
)
from meeting_pipeline.asr.cache import AsrCache, compute_asr_cache_key, decoding_fingerprint
from meeting_pipeline.asr.quality import check_asr_quality
from meeting_pipeline.asr.router import (
    AdaptiveAsrRouter,
    TranscriptPreQuality,
    evaluate_source_pre_quality_for_asr,
)
from meeting_pipeline.audio.coverage import covers, interval_metadata
from meeting_pipeline.audio.signal_fusion import ASR_AUDIO_INPUT_ID, afftdn, fuse_sources
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
    core_end_inclusive: bool = True,
    internal_start: bool = False,
    internal_end: bool | None = None,
    asr_chunk_group_id: str | None = None,
    asr_input_path: Path | None = None,
) -> tuple[dict[str, SourceHypothesis], dict[str, Any]]:
    """Transcribe with hard speaker bounds and auditable word ownership."""
    internal_end = not core_end_inclusive if internal_end is None else internal_end
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
        s_idx = max(0, round(clip_start_sec * sample_rate))
        e_idx = min(len(full_sig), round(clip_end_sec * sample_rate))
        clip = full_sig[s_idx:e_idx] if e_idx > s_idx else np.zeros(0, dtype=np.float32)
        sliced_clips[src_id] = clip

        sync_status = interval_metadata(
            sync_metadata.get(src_id, {}), core_start_sec, core_end_sec
        ).get("status", "synchronized")
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
        if not covers(sync_metadata.get(src_id, {}), core_start_sec, core_end_sec):
            pre_qual.is_eligible = False
            pre_qual.exclusion_reason = "outside_recorded_coverage"
            pre_qual.pre_score = 0.0

    router = AdaptiveAsrRouter(mode=asr_config.routing_mode)
    ranked = [
        quality
        for quality in router.rank_sources(pre_qualities)
        if quality.exclusion_reason != "outside_recorded_coverage"
    ]
    audio_fusion = asr_config.fusion_mode == "audio"
    preparation: dict[str, Any] = {}
    if audio_fusion:
        ranked = [q for q in ranked if q.exclusion_reason != "alignment_failed"]
        initial_sources = []
        if ranked:
            reference = ranked[0]
            ref_id = reference.source_id
            clip = sliced_clips[ref_id]
            contributors = {ref_id: 1.0}
            preparation = {
                "reference_source_id": ref_id,
                "fallback_reason": "no_eligible_secondary",
            }
            eligible_secondaries = [q for q in ranked[1:] if q.is_eligible]
            if reference.is_eligible and eligible_secondaries:
                secondary_id = eligible_secondaries[0].source_id
                source_specs = [
                    (
                        q.source_id,
                        sliced_clips[q.source_id],
                        sync_metadata.get(q.source_id, {}),
                        max(q.pre_score, 1e-4),
                    )
                    for q in (reference, *eligible_secondaries)
                ]
                clip, details = fuse_sources(
                    source_specs,
                    clip_start=round(clip_start_sec * sample_rate),
                    core=(round(core_start_sec * sample_rate), round(core_end_sec * sample_rate)),
                    sample_rate=sample_rate,
                )
                fused_contributors = details.pop("contributors", None)
                preparation.update(details, secondary_candidate_id=secondary_id)
                if "fallback_reason" not in details and fused_contributors:
                    preparation.pop("fallback_reason")
                    contributors = fused_contributors
            preparation["source_weights"] = contributors
            preparation["method"] = "delay_and_sum" if len(contributors) > 1 else "best_mic"
            preparation["denoise_requested"] = asr_config.audio_denoise
            preparation["denoise_used"] = "none"
            if asr_config.audio_denoise == "afftdn" and len(clip) >= sample_rate // 20:
                try:
                    clip = afftdn(clip, sample_rate)
                    preparation["denoise_used"] = "afftdn"
                except (OSError, subprocess.SubprocessError, ValueError) as exc:
                    logger.warning("afftdn failed for turn %s: %s", turn_id, exc)
                    preparation["denoise_fallback_reason"] = "filter_failed"
            sliced_clips[ASR_AUDIO_INPUT_ID] = clip
            initial_sources = [ASR_AUDIO_INPUT_ID]
            if asr_input_path is not None:
                asr_input_path.parent.mkdir(parents=True, exist_ok=True)
                sf.write(asr_input_path, clip, sample_rate, subtype="FLOAT")
    else:
        initial_sources = router.select_initial_sources(ranked)

    scheduled_sources: list[str] = list(initial_sources)
    routing_reasons: dict[str, str] = {
        src: "prepared_mono" if audio_fusion else "scheduled_initial" for src in scheduled_sources
    }

    hypotheses: dict[str, SourceHypothesis] = {}

    adapter_calls = 0
    cache_hits = 0

    def _decode_source(source_id: str, reason: str) -> SourceHypothesis:
        nonlocal adapter_calls, cache_hits
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
            decoding_settings=decoding_fingerprint(asr_config),
        )

        asr_res: AsrResult | None = None
        if cache is not None:
            asr_res = cache.get(cache_key)

        if asr_res is None:
            try:
                adapter_calls += 1
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
        else:
            cache_hits += 1

        asr_status = asr_res.status
        asr_warnings = list(asr_res.warnings)
        if dur < 1.0:
            asr_warnings.append("asr_short_context")
        raw_candidates = list(asr_res.raw_candidates)

        words, boundary_audit = filter_boundary_words(
            asr_res,
            turn_id=turn_id,
            core=(core_start_sec, core_end_sec),
            clip=(clip_start_sec, clip_end_sec),
            internal_start=internal_start,
            internal_end=internal_end,
            end_inclusive=core_end_inclusive,
        )

        # Raw decoder cache remains reusable; ownership is applied after cache reads.
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

        hypothesis = SourceHypothesis(
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
            word_boundary_audit=boundary_audit,
            audio_quality_score=round(audio_q_score, 4),
            transcript_quality_score=round(transcript_q_score, 4),
            routing_reason=reason,
        )
        refresh_boundary_hypothesis(hypothesis)
        return hypothesis

    # Decode initial scheduled sources
    for src_id in scheduled_sources:
        hypotheses[src_id] = _decode_source(src_id, routing_reasons[src_id])

    # In adaptive mode, check if top-2 should be scheduled
    if (
        not audio_fusion
        and asr_config.routing_mode == "adaptive"
        and len(ranked) >= 2
        and len(scheduled_sources) < asr_config.max_verification_sources
    ):
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

    # Acoustic pre-score is not recognition confidence. A further clean source
    # can resolve rejected candidates or lexical disagreement between two mics.
    if not audio_fusion and asr_config.routing_mode == "adaptive":
        for quality in ranked:
            if len(scheduled_sources) >= asr_config.max_verification_sources:
                break
            if quality.source_id in scheduled_sources or not quality.is_eligible:
                continue
            accepted = [h for h in hypotheses.values() if h.asr_status == "transcribed" and h.text]
            disagreement = len({h.text for h in accepted}) > 1
            rejected = any(h.asr_status != "transcribed" or not h.text for h in hypotheses.values())
            uncertain = any(
                set(h.asr_warnings).intersection({"asr_short_context", "asr_retry_succeeded"})
                for h in hypotheses.values()
            )
            if not (disagreement or rejected or uncertain):
                break
            reason = (
                "source_disagreement"
                if disagreement
                else "source_rejected"
                if rejected
                else "short_or_retried_context"
            )
            scheduled_sources.append(quality.source_id)
            routing_reasons[quality.source_id] = "scheduled_verification_" + reason
            hypotheses[quality.source_id] = _decode_source(
                quality.source_id, routing_reasons[quality.source_id]
            )

    accepted_sources = [h for h in hypotheses.values() if h.asr_status == "transcribed" and h.text]
    if not audio_fusion and len(accepted_sources) == 1:
        accepted_sources[0].asr_warnings.append("asr_single_source_unverified")
        if (
            core_end_sec - core_start_sec < 0.5
            and accepted_sources[0].asr_features.get("mean_confidence") is None
            and any(h.asr_status in {"unreliable", "failed"} for h in hypotheses.values())
        ):
            # Quarantine an unconfirmed micro-fragment after actual cross-source
            # failure. Single-mic interjections and corroborated short answers
            # remain valid; the raw candidate and audio are retained for review.
            accepted_sources[0].asr_status = "unreliable"
            accepted_sources[0].asr_warnings.append("asr_unverified_short_fragment")
            accepted_sources[0].transcript_quality_score = 0.0

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
            routing_reason=(
                "prepared_mono_only" if audio_fusion else "gated_out_by_adaptive_routing"
            ),
        )

    routing_metadata = {
        "turn_id": turn_id,
        "core_interval": [round(core_start_sec, 3), round(core_end_sec, 3)],
        "clip_interval": [round(clip_start_sec, 3), round(clip_end_sec, 3)],
        "routing_mode": "audio_fusion" if audio_fusion else asr_config.routing_mode,
        "scheduled_sources": scheduled_sources,
        "adapter_calls": adapter_calls,
        "cache_hits": cache_hits,
        "abstained_sources": unscheduled,
        "ranked_pre_qualities": [q.as_dict() for q in ranked],
        "word_boundary_policy": BOUNDARY_POLICY_VERSION,
        "asr_chunk_group_id": asr_chunk_group_id,
        "decoding_fingerprint": decoding_fingerprint(asr_config),
        "start_boundary_kind": "internal" if internal_start else "speaker_or_silence",
        "end_boundary_kind": "internal" if internal_end else "speaker_or_silence",
    }
    if audio_fusion:
        routing_metadata["audio_fusion"] = preparation or {"fallback_reason": "no_recorded_source"}

    return hypotheses, routing_metadata
