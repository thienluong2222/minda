"""Safe turn merging for consecutive single-speaker turns in the same cluster.

Specification: Section 7.1 of docs/PLAN_VAD_SPEAKER_ASR_MULTI_SOURCE_2026-10-03.md.
Ensures no cross-speaker contamination while reducing ASR calls on short sub-turns.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np

from meeting_pipeline.config import AsrConfig
from meeting_pipeline.domain.transcription import SpeechRegion
from meeting_pipeline.pipeline.speaker_turns import SpeakerTurn
from meeting_pipeline.pipeline.stages.chunking import plan_region_chunks
from meeting_pipeline.speaker.clustering import TurnAssignment

logger = logging.getLogger(__name__)


@dataclass
class MergedSpeakerTurn:
    """Consolidated speech turn representing one continuous speaking period by one cluster."""

    turn_id: str
    start_sec: float
    end_sec: float
    speaker_count: int
    sub_turn_ids: list[str]
    cluster_id: str | None
    meeting_speaker_id: str | None
    speaker_label: str
    speaker_status: str
    speech_region_id: str
    track_id: str
    warnings: list[str] = field(default_factory=list)
    needs_review: bool = False
    source_evidence: list[dict[str, Any]] = field(default_factory=list)
    overlap_group_id: str | None = None
    asr_chunk_group_id: str | None = None

    @property
    def duration_sec(self) -> float:
        return self.end_sec - self.start_sec

    def as_speaker_turn(self) -> SpeakerTurn:
        """Expose standard SpeakerTurn view for backwards compatibility."""
        return SpeakerTurn(
            turn_id=self.turn_id,
            start_sec=self.start_sec,
            end_sec=self.end_sec,
            speech_region_id=self.speech_region_id,
            track_id=self.track_id,
            speaker_count=self.speaker_count,
            overlap_group_id=self.overlap_group_id,
            warnings=list(self.warnings),
        )


def safe_merge_speaker_turns(
    turns: list[SpeakerTurn],
    assignments: dict[str, TurnAssignment],
    max_merge_gap_sec: float = 0.6,
    max_core_sec: float = 22.0,
    enabled: bool = True,
    hard_boundaries: list[float] | None = None,
) -> list[MergedSpeakerTurn]:
    """Group consecutive single-speaker turns belonging to the exact same cluster.

    Rules:
    - Never merge across different speaker clusters or ambiguous/overlap turns.
    - Never merge across a time gap exceeding max_merge_gap_sec.
    - Never allow the consolidated duration to exceed max_core_sec.
    """
    if not turns:
        return []

    if not enabled:
        # Pass-through 1-to-1 conversion
        merged_turns: list[MergedSpeakerTurn] = []
        for t in turns:
            assign = assignments.get(t.turn_id)
            c_id = assign.cluster_id if assign else None
            m_id = assign.meeting_speaker_id if assign else None
            lbl = assign.speaker_label if assign else ("Nói chồng" if t.speaker_count == 2 else "")
            stat = assign.speaker_status if assign else "unknown"
            review = assign.needs_review if assign else (t.speaker_count == 2)
            ev = assign.source_evidence if assign else []

            merged_turns.append(
                MergedSpeakerTurn(
                    turn_id=t.turn_id,
                    start_sec=t.start_sec,
                    end_sec=t.end_sec,
                    speaker_count=t.speaker_count,
                    sub_turn_ids=[t.turn_id],
                    cluster_id=c_id,
                    meeting_speaker_id=m_id,
                    speaker_label=lbl,
                    speaker_status=stat,
                    speech_region_id=t.speech_region_id,
                    track_id=t.track_id,
                    warnings=list(t.warnings),
                    needs_review=review,
                    source_evidence=ev,
                    overlap_group_id=t.overlap_group_id,
                )
            )
        return merged_turns

    # Sort turns chronologically
    sorted_turns = sorted(turns, key=lambda t: (t.start_sec, t.end_sec))
    merged: list[MergedSpeakerTurn] = []

    current_group: list[SpeakerTurn] = []
    current_assign: TurnAssignment | None = None

    def flush_group() -> None:
        nonlocal current_group, current_assign
        if not current_group:
            return

        first = current_group[0]
        last = current_group[-1]
        sub_ids = [t.turn_id for t in current_group]
        merged_id = (
            first.turn_id if len(current_group) == 1 else f"merged-{first.turn_id}-{last.turn_id}"
        )

        # Combine warnings and evidence
        all_warnings: list[str] = []
        for t in current_group:
            all_warnings.extend(t.warnings)

        c_id = current_assign.cluster_id if current_assign else None
        m_id = current_assign.meeting_speaker_id if current_assign else None
        lbl = current_assign.speaker_label if current_assign else ""
        stat = current_assign.speaker_status if current_assign else "unknown"
        review = current_assign.needs_review if current_assign else False
        ev = current_assign.source_evidence if current_assign else []

        merged.append(
            MergedSpeakerTurn(
                turn_id=merged_id,
                start_sec=first.start_sec,
                end_sec=last.end_sec,
                speaker_count=1,
                sub_turn_ids=sub_ids,
                cluster_id=c_id,
                meeting_speaker_id=m_id,
                speaker_label=lbl,
                speaker_status=stat,
                speech_region_id=first.speech_region_id,
                track_id=first.track_id,
                warnings=list(dict.fromkeys(all_warnings)),
                needs_review=review,
                source_evidence=ev,
            )
        )
        current_group = []
        current_assign = None

    for turn in sorted_turns:
        assign = assignments.get(turn.turn_id)

        # Overlap turns (speaker_count == 2) can never be merged
        if turn.speaker_count == 2:
            flush_group()
            lbl = assign.speaker_label if assign else "Nói chồng"
            stat = assign.speaker_status if assign else "ambiguous"
            ev = assign.source_evidence if assign else []
            merged.append(
                MergedSpeakerTurn(
                    turn_id=turn.turn_id,
                    start_sec=turn.start_sec,
                    end_sec=turn.end_sec,
                    speaker_count=2,
                    sub_turn_ids=[turn.turn_id],
                    cluster_id=None,
                    meeting_speaker_id=None,
                    speaker_label=lbl,
                    speaker_status=stat,
                    speech_region_id=turn.speech_region_id,
                    track_id=turn.track_id,
                    warnings=list(turn.warnings),
                    needs_review=True,
                    source_evidence=ev,
                    overlap_group_id=turn.overlap_group_id,
                )
            )
            continue

        # Ambiguous turns or unassigned turns should not be merged
        is_ambiguous = assign is None or assign.needs_review or assign.speaker_status == "ambiguous"
        if is_ambiguous:
            flush_group()
            lbl = assign.speaker_label if assign else "Chưa xác định"
            stat = assign.speaker_status if assign else "ambiguous"
            ev = assign.source_evidence if assign else []
            merged.append(
                MergedSpeakerTurn(
                    turn_id=turn.turn_id,
                    start_sec=turn.start_sec,
                    end_sec=turn.end_sec,
                    speaker_count=1,
                    sub_turn_ids=[turn.turn_id],
                    cluster_id=None,
                    meeting_speaker_id=None,
                    speaker_label=lbl,
                    speaker_status=stat,
                    speech_region_id=turn.speech_region_id,
                    track_id=turn.track_id,
                    warnings=list(turn.warnings),
                    needs_review=True,
                    source_evidence=ev,
                )
            )
            continue

        if not current_group:
            current_group = [turn]
            current_assign = assign
            continue

        # Check merge eligibility with current group
        last_turn = current_group[-1]
        same_cluster = (
            current_assign is not None
            and assign is not None
            and assign.cluster_id is not None
            and assign.cluster_id == current_assign.cluster_id
            and assign.meeting_speaker_id == current_assign.meeting_speaker_id
        )
        gap = turn.start_sec - last_turn.end_sec
        new_total_duration = turn.end_sec - current_group[0].start_sec
        crosses_boundary = any(
            current_group[0].start_sec + 1e-6 < boundary < turn.end_sec - 1e-6
            for boundary in hard_boundaries or []
        )

        if (
            same_cluster
            and 0.0 <= gap <= max_merge_gap_sec
            and new_total_duration <= max_core_sec
            and not crosses_boundary
        ):
            current_group.append(turn)
        else:
            flush_group()
            current_group = [turn]
            current_assign = assign

    flush_group()
    return merged


def split_merged_turns_for_asr(
    turns: list[MergedSpeakerTurn],
    asr_config: AsrConfig,
    audio: np.ndarray,
    sample_rate: int,
) -> list[MergedSpeakerTurn]:
    """Limit ASR clips after identity assignment, keeping context across internal cuts."""
    result: list[MergedSpeakerTurn] = []
    for turn in turns:
        if turn.speaker_count != 1:
            result.append(turn)
            continue
        chunks = plan_region_chunks(
            SpeechRegion(
                region_id=turn.turn_id,
                start_sec=turn.start_sec,
                end_sec=turn.end_sec,
                supporting_source_ids=[],
                source_intervals={},
            ),
            asr_config,
            len(audio) / sample_rate,
            audio_samples=audio,
            sample_rate=sample_rate,
        )
        if len(chunks) == 1:
            result.append(turn)
            continue
        for index, chunk in enumerate(chunks):
            result.append(
                replace(
                    turn,
                    turn_id=f"{turn.turn_id}-asr-{index:03d}",
                    start_sec=chunk.core_interval.start_sec,
                    end_sec=chunk.core_interval.end_sec,
                    asr_chunk_group_id=turn.turn_id,
                )
            )
    return result


def asr_context_boundaries(
    turns: list[MergedSpeakerTurn],
    index: int,
) -> tuple[float | None, float | None]:
    """Keep real speaker boundaries hard while allowing context inside one ASR group."""
    turn = turns[index]
    previous = turns[index - 1] if index else None
    following = turns[index + 1] if index + 1 < len(turns) else None

    def same_group(other: MergedSpeakerTurn | None) -> bool:
        return bool(
            other is not None
            and turn.asr_chunk_group_id
            and turn.asr_chunk_group_id == other.asr_chunk_group_id
        )

    # Across internal cuts, still cap context at the outer speaker/overlap bounds.
    left_index = index
    while left_index > 0 and same_group(turns[left_index - 1]):
        left_index -= 1
    right_index = index
    while right_index + 1 < len(turns) and same_group(turns[right_index + 1]):
        right_index += 1
    left = turns[left_index - 1].end_sec if left_index else 0.0
    right = turns[right_index + 1].start_sec if right_index + 1 < len(turns) else None
    return (
        left if same_group(previous) else (previous.end_sec if previous else 0.0),
        right if same_group(following) else (following.start_sec if following else None),
    )
