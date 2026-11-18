"""Join continuous speech without losing the original evidence boundaries."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from meeting_pipeline.minutes.evidence_retrieval import IndexedTurn
from meeting_pipeline.minutes.schemas import EvidenceRef

NUMBER_WORDS = (
    r"\d+|không|một|hai|ba|bốn|tư|năm|lăm|sáu|bảy|tám|chín|mười|mươi|trăm|"
    r"nghìn|ngàn|triệu|linh|lẻ"
)
START_NUMBER = re.compile(rf"^(?:{NUMBER_WORDS})\b", re.I)
END_NUMBER = re.compile(rf"\b(?:{NUMBER_WORDS}|ngày|tháng|lúc|giờ|phút)\s*$", re.I)
NEW_STATEMENT = re.compile(
    r"^(?:tôi |chúng ta |thành phần |kết quả |cuộc họp |toàn bộ |nội dung |"
    r"phương án |về việc |vấn đề |chuyển sang |thêm |bây giờ |vậy )",
    re.I,
)


@dataclass
class TranscriptSpan:
    turns: list[IndexedTurn] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(turn.text.strip() for turn in self.turns)

    def sources(self, start: int = 0, end: int | None = None) -> list[IndexedTurn]:
        end = len(self.text) if end is None else end
        offset = 0
        result = []
        for turn in self.turns:
            right = offset + len(turn.text.strip())
            if offset < end and right > start:
                result.append(turn)
            offset = right + 1
        return result


def context_spans(turns: list[IndexedTurn]) -> list[TranscriptSpan]:
    """Bounded joins respect exclusions, clocks, sessions and temporal gaps."""
    spans: list[TranscriptSpan] = []
    current = None
    for turn in turns:
        if not turn.text.strip() or turn.asr_status not in {"transcribed", "user_edited"}:
            current = None
            continue
        previous = current.turns[-1] if current else None
        continuous = (
            previous is not None
            and previous.clock_id == turn.clock_id
            and previous.session_id == turn.session_id
            and -0.05 <= turn.start_sec - previous.end_sec <= 1.5
            and len(current.text.split()) + len(turn.text.split()) <= 180
        )
        join = False
        if continuous and current is not None and previous is not None:
            parent = re.sub(r"-part-\d+$", "", previous.turn_id)
            same_region = parent != previous.turn_id and parent == re.sub(
                r"-part-\d+$", "", turn.turn_id
            )
            number_continuation = END_NUMBER.search(previous.text) and START_NUMBER.search(
                turn.text
            )
            same_speaker = (
                previous.meeting_speaker_id == turn.meeting_speaker_id
                if previous.meeting_speaker_id and turn.meeting_speaker_id
                else previous.speaker_label == turn.speaker_label
            )
            continuation = (
                same_speaker
                and not re.search(r"[.!?;]$", previous.text.strip())
                and not NEW_STATEMENT.search(turn.text.strip())
            )
            join = bool(same_region or number_continuation or continuation)
        if not join:
            current = TranscriptSpan()
            spans.append(current)
        assert current is not None
        current.turns.append(turn)
    return spans


def evidence_refs(turns: list[IndexedTurn], run_id: str) -> list[EvidenceRef]:
    return [
        EvidenceRef(
            run_id=run_id,
            turn_id=turn.turn_id,
            source_id=turn.source_id,
            start_sec=turn.start_sec,
            end_sec=turn.end_sec,
            clip_path=turn.clip_path,
            clip_artifact_id=turn.clip_artifact_id,
            text_snippet=turn.text,
        )
        for turn in {turn.turn_id: turn for turn in turns}.values()
    ]
