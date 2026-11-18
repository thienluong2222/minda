"""Lossless source spans and bounded units for meetings of any length."""

from __future__ import annotations

import re
from itertools import pairwise
from typing import Any

from meeting_pipeline.minutes.evidence_retrieval import IndexedTurn
from meeting_pipeline.minutes.graph_contracts import GraphUnit, SourceSpan, digest


def clause_spans(text: str, start: int, end: int, subjects: set[str]):
    """Split explicit new acts, retaining every character and conditional scope."""
    actors = "|".join(re.escape(name) for name in sorted(subjects, key=len, reverse=True) if name)
    patterns = [
        r"(?:tôi\s+(?:cũng\s+)?(?:đề nghị|xác nhận|sẽ|nhận việc|kết luận)"
        r"|bây giờ\s+tôi|nhưng\s|tuy nhiên\s)"
    ]
    if actors:
        patterns.append(rf"(?:{actors})\s+(?:gửi|nhập|kiểm tra|rà soát|phụ trách)\b")
    boundaries = [start]
    for match in re.finditer(rf"(?<!\w)(?:{'|'.join(patterns)})", text[start:end], re.I):
        position = start + match.start()
        prefix = text[boundaries[-1] : position]
        if len(prefix.split()) < 3 or re.search(r"\b(?:nếu|chỉ khi|trừ khi)\b", prefix, re.I):
            continue
        boundaries.append(position)
    boundaries.append(end)
    for left, right in pairwise(boundaries):
        while left < right and text[left].isspace():
            left += 1
        while right > left and text[right - 1].isspace():
            right -= 1
        if left < right:
            yield left, right


def make_graph_units(
    turns: list[IndexedTurn],
    metadata: dict[str, Any] | None = None,
) -> tuple[list[GraphUnit], list[dict[str, str]]]:
    metadata = metadata or {}
    subjects = set()
    for turn in turns:
        label = re.split(r"\s+[\u2014\u2013]\s+", turn.speaker_label)[0].strip()
        if label and not re.match(r"người lạ|chưa xác định|speaker|unknown", label, re.I):
            subjects.add(label)
        subjects.update(re.findall(r"\b(?:anh|chị|ông|bà|tôi là)\s+([^\W\d_]+)", turn.text, re.I))
    sessions = metadata.get("turn_sessions", {})
    units, excluded = [], []
    episode = -1
    previous_session = None
    count_in_episode = 0
    for turn in turns:
        if not turn.text.strip() or turn.asr_status not in {"transcribed", "user_edited"}:
            excluded.append({"turn_id": turn.turn_id, "reason": turn.asr_status})
            continue
        session = str(sessions.get(turn.turn_id, "session_0"))
        sentences = list(re.finditer(r"\S.*?(?:[.!?;](?=\s|$)|$)", turn.text, re.S))
        spans = [
            span
            for match in sentences
            for span in clause_spans(turn.text, match.start(), match.end(), subjects)
        ]
        for span_left, span_right in spans:
            words = list(re.finditer(r"\S+", turn.text[span_left:span_right]))
            # A bounded source unit, not an assumed word timestamp.
            for offset in range(0, len(words), 55):
                part = words[offset : offset + 55]
                left = span_left + part[0].start()
                right = span_left + part[-1].end()
                text = turn.text[left:right]
                transition = bool(
                    re.search(
                        r"(?:chuyển sang|tiếp theo.*(?:nội dung|vấn đề)|phiên họp|khai mạc)",
                        text,
                        re.I,
                    )
                )
                if session != previous_session or count_in_episode >= 18 or transition:
                    episode += 1
                    count_in_episode = 0
                unit_id = "u_" + digest([turn.turn_id, left, right, text])[:16]
                units.append(
                    GraphUnit(
                        unit_id=unit_id,
                        turn_id=turn.turn_id,
                        turn_ids=[turn.turn_id],
                        speaker=turn.speaker_label,
                        speaker_id=turn.speaker_id,
                        session_id=session,
                        episode_id=f"episode_{episode}",
                        start_sec=turn.start_sec,
                        end_sec=turn.end_sec,
                        original=text,
                        text=text,
                        needs_review=turn.needs_review,
                        user_edited=turn.asr_status == "user_edited",
                        sources=[
                            SourceSpan(
                                turn_id=turn.turn_id,
                                start_char=left,
                                end_char=right,
                                text=text,
                                source_id=turn.source_id,
                                start_sec=turn.start_sec,
                                end_sec=turn.end_sec,
                            )
                        ],
                    )
                )
                previous_session = session
                count_in_episode += 1
    return units, excluded


def contextual_texts(units: list[GraphUnit]) -> list[str]:
    texts = []
    for i, unit in enumerate(units):
        text = unit.text
        if (
            i
            and units[i - 1].session_id == unit.session_id
            and (
                len(text.split()) < 9
                or re.search(r"\b(?:đó|này|vậy|đồng ý|nhất trí)\b", text, re.I)
            )
        ):
            # The contextual unit retains its own source identity.
            text = units[i - 1].text + " " + text
        texts.append(text)
    return texts


def resplit_units(units: list[GraphUnit]) -> list[GraphUnit]:
    """Upgrade frozen source units without changing original turn coordinates."""
    subjects = set()
    for unit in units:
        subjects.update(
            re.findall(r"\b(?:anh|chị|ông|bà|tôi là)\s+([^\W\d_]+)", unit.original, re.I)
        )
        if unit.speaker and not re.match(
            r"người lạ|chưa xác định|speaker|unknown", unit.speaker, re.I
        ):
            subjects.add(re.split(r"\s+[\u2014\u2013]\s+", unit.speaker)[0])
    result = []
    for unit in units:
        if (
            unit.text != unit.original
            or len(unit.sources) != 1
            or unit.sources[0].text != unit.original
        ):
            result.append(unit)
            continue
        spans = list(clause_spans(unit.original, 0, len(unit.original), subjects))
        if len(spans) == 1:
            result.append(unit)
            continue
        source = unit.sources[0]
        for left, right in spans:
            text = unit.original[left:right]
            span = source.model_copy(
                update={
                    "start_char": source.start_char + left,
                    "end_char": source.start_char + right,
                    "text": text,
                }
            )
            uid = "u_" + digest([unit.turn_id, span.start_char, span.end_char, text])[:16]
            result.append(
                unit.model_copy(
                    update={"unit_id": uid, "original": text, "text": text, "sources": [span]}
                )
            )
    return result
