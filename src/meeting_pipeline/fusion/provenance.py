"""Provenance tracking, primary source attribution, and evidence audio extraction.

Specification: Section 5.5 & 13.1 of docs/PLAN_VIVOS_SYNTHETIC_PIPELINE.md.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from meeting_pipeline.domain.contracts import (
    FinalTimelineItem,
    MeetingSegment,
    SourceHypothesis,
    WordProvenance,
)

logger = logging.getLogger(__name__)


def build_final_timeline_item(
    meeting_id: str,
    segment: MeetingSegment,
    fused_text: str,
    word_decisions: list[dict[str, Any]],
    speaker_id: str,
    speaker_confidence: float,
    source_hypotheses: dict[str, SourceHypothesis],
    aligned_audio_signals: dict[str, np.ndarray[Any, np.dtype[np.float32]]],
    output_clips_dir: Path | str | None = None,
    sample_rate: int = 16000,
) -> FinalTimelineItem:
    """Build a comprehensive FinalTimelineItem with word provenance and evidence clips."""
    # 1. Source scores
    source_scores = {s_id: hyp.transcript_quality_score for s_id, hyp in source_hypotheses.items()}

    # The fusion vote is relative support, not a calibrated probability of
    # correctness. With one valid source, even relative agreement is undefined.
    valid_source_count = sum(
        hypothesis.asr_status == "transcribed" and bool(hypothesis.text.strip())
        for hypothesis in source_hypotheses.values()
    )

    # 2. Build WordProvenance records
    provenance_list: list[WordProvenance] = []
    source_contributions: dict[str, float] = {s_id: 0.0 for s_id in source_hypotheses}

    for d in word_decisions:
        word = d["word"]
        conf = float(d["confidence"])
        supporting = d["supporting_sources"]
        rep_src = d["representative_source_id"]

        per_source_scores = {s: source_scores.get(s, 0.5) for s in supporting}
        for s in supporting:
            source_contributions[s] += source_scores.get(s, 0.5)

        provenance_list.append(
            WordProvenance(
                output_word=word,
                confidence=round(conf, 3) if valid_source_count > 1 else None,
                supporting_sources=supporting,
                source_scores={s: round(sc, 3) for s, sc in per_source_scores.items()},
                representative_source_id=rep_src,
            )
        )

    # 3. Determine primary_source_id: source with highest total contribution
    if source_contributions:
        primary_source = max(source_contributions.keys(), key=lambda s: source_contributions[s])
    else:
        primary_source = sorted(source_hypotheses.keys())[0] if source_hypotheses else "unknown"

    # 4. Extract and save evidence audio clips
    evidence_clips: dict[str, str] = {}
    if output_clips_dir is not None:
        clips_p = Path(output_clips_dir) / meeting_id / segment.segment_id
        clips_p.mkdir(parents=True, exist_ok=True)

        s_samp = round(segment.start_sec * sample_rate)
        e_samp = round(segment.end_sec * sample_rate)

        for dev_id, sig in aligned_audio_signals.items():
            clip_path = clips_p / f"{dev_id}.wav"
            if len(sig) > s_samp:
                clip_data = sig[s_samp:e_samp]
            else:
                clip_data = np.zeros(0, dtype=np.float32)

            try:
                sf.write(str(clip_path), clip_data, sample_rate, subtype="PCM_16")
                evidence_clips[dev_id] = str(clip_path)
            except Exception as exc:
                logger.warning("Failed to write evidence clip for %s: %s", dev_id, exc)

    return FinalTimelineItem(
        schema_version="1.0",
        meeting_id=meeting_id,
        segment_id=segment.segment_id,
        start_sec=segment.start_sec,
        end_sec=segment.end_sec,
        speaker_id=speaker_id,
        speaker_confidence=round(speaker_confidence, 4),
        text=fused_text,
        transcript_confidence=None,
        primary_source_id=primary_source,
        source_scores={s: round(sc, 4) for s, sc in source_scores.items()},
        word_provenance=provenance_list,
        evidence_clips=evidence_clips,
    )
