"""Conservative Vietnamese metadata normalization independent of generated prose."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from meeting_pipeline.minutes.evidence_retrieval import IndexedTurn
from meeting_pipeline.minutes.fact_extractor import M2RuleFactExtractor
from meeting_pipeline.minutes.schemas import (
    DocGraph,
    EvidenceRef,
    FactStatus,
    MeetingFact,
    PlaceholderType,
    SemanticFieldType,
    TemplateSchema,
)

WORDS = {
    "không": 0,
    "một": 1,
    "hai": 2,
    "ba": 3,
    "bốn": 4,
    "tư": 4,
    "năm": 5,
    "lăm": 5,
    "sáu": 6,
    "bảy": 7,
    "tám": 8,
    "chín": 9,
}
NUM = (
    r"(?:\d+|không|một|hai|ba|bốn|tư|năm|lăm|sáu|bảy|tám|chín|mười|mươi|trăm|"
    r"nghìn|ngàn|triệu|linh|lẻ)"
)
PHRASE = rf"{NUM}(?:\s+{NUM})*"


def vietnamese_number(text: str) -> int:
    text = text.strip().lower()
    if text.isdigit():
        return int(text)
    tokens = text.split()
    if not tokens or any(
        t not in WORDS
        and t
        not in {
            "mười",
            "mươi",
            "trăm",
            "nghìn",
            "ngàn",
            "triệu",
            "linh",
            "lẻ",
        }
        for t in tokens
    ):
        raise ValueError("Không nhận dạng được số tiếng Việt.")
    if all(t in WORDS for t in tokens):
        return int("".join(str(WORDS[t]) for t in tokens))
    total = group = current = 0
    for token in tokens:
        if token in WORDS:
            current = WORDS[token]
        elif token in {"linh", "lẻ"}:
            continue
        elif token in {"mười", "mươi"}:
            group += (current or 1) * 10
            current = 0
        elif token == "trăm":
            group += current * 100
            current = 0
        else:
            total += (group + current) * (1000000 if token == "triệu" else 1000)
            group = current = 0
    return total + group + current


def structured_facts(
    schema: TemplateSchema,
    graph: DocGraph,
    turns: list[IndexedTurn],
    run_id: str,
    meeting_metadata: dict[str, Any] | None = None,
) -> list[MeetingFact]:
    baseline = M2RuleFactExtractor().extract_facts(
        schema, turns, meeting_metadata=meeting_metadata, run_id=run_id
    )
    facts = {f.field_id: f for f in baseline}
    valid = [t for t in turns if t.text and t.asr_status in {"transcribed", "user_edited"}]
    anchors = {a.anchor_id: a for a in graph.all_anchors}
    blocks = {b.block_id: b for b in graph.blocks}
    values: dict[str, tuple[str, IndexedTurn]] = {}
    for turn in valid:
        text = turn.text.casefold()
        for match in re.finditer(
            rf"ngày\s+({PHRASE})\s+tháng\s+({PHRASE})\s+năm\s+({PHRASE})", text
        ):
            try:
                d, m, y = (vietnamese_number(s) for s in match.groups())
                date(y, m, d)
                for key, value in (("day", d), ("month", m), ("year", y)):
                    values.setdefault(key, (str(value), turn))
                    if "kết thúc" in text:
                        values.setdefault("end_" + key, (str(value), turn))
            except ValueError:
                pass
        time_match = re.search(rf"lúc\s+({PHRASE})\s+giờ(?:\s+({PHRASE})\s+phút)?", text)
        if time_match:
            h = vietnamese_number(time_match.group(1))
            minute = vietnamese_number(time_match.group(2)) if time_match.group(2) else 0
            kind = (
                "end"
                if "kết thúc" in text
                else "start"
                if any(word in text for word in ("bắt đầu", "hôm nay", "khai mạc"))
                else None
            )
            if kind and h < 24 and minute < 60:
                values.setdefault(kind + "_hour", (str(h), turn))
                values.setdefault(kind + "_minute", (f"{minute:02d}", turn))
        location = re.search(r"\btại\s+([^.!?]+)", turn.text, re.IGNORECASE)
        if location:
            room = re.split(
                r"\b(?:đây là|cuộc họp|về việc)\b",
                location.group(1),
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0].strip(" ,;:")
            number = re.search(rf"\b([A-Z]|bê|xê|đê)\s+({PHRASE})$", room, re.IGNORECASE)
            if number:
                letter = {"bê": "B", "xê": "C", "đê": "D"}.get(
                    number.group(1).casefold(), number.group(1).upper()
                )
                room = room[: number.start()] + letter + str(vietnamese_number(number.group(2)))
            values.setdefault("location", (room, turn))
        topic = re.search(r"\bvề việc\s+([^.!?]+)", turn.text, re.IGNORECASE)
        if topic:
            values.setdefault("topic", (topic.group(1).strip(), turn))
        for kind, pattern in (
            ("vote_total", rf"tổng số\s+({PHRASE})\s+phiếu"),
            ("vote_yes", rf"({PHRASE})\s+phiếu tán thành"),
            ("vote_no", rf"({PHRASE})\s+phiếu không tán thành"),
        ):
            vote_match = re.search(pattern, text)
            if vote_match:
                values[kind] = str(vietnamese_number(vote_match.group(1))), turn
        if re.search(r"không có phiếu không tán thành", text):
            values["vote_no"] = "0", turn
    if "end_hour" in values and "cùng ngày" in values["end_hour"][1].text.casefold():
        for key in ("day", "month", "year"):
            if key in values:
                values.setdefault("end_" + key, values[key])
    if all(k in values for k in ("vote_total", "vote_yes", "vote_no")):
        total, yes, no = (int(values[k][0]) for k in ("vote_total", "vote_yes", "vote_no"))
        if total > 0 and yes + no == total:
            values["yes_percent"] = f"{100 * yes / total:g}", values["vote_yes"][1]
            values["no_percent"] = f"{100 * no / total:g}", values["vote_no"][1]

    scalar_types = {
        SemanticFieldType.MEETING_LOCATION: "location",
        SemanticFieldType.MEETING_TOPIC: "topic",
        SemanticFieldType.MEETING_AGENDA_SUMMARY: "topic",
        SemanticFieldType.VOTING_TOTAL: "vote_total",
        SemanticFieldType.VOTING_APPROVED_COUNT: "vote_yes",
        SemanticFieldType.VOTING_REJECTED_COUNT: "vote_no",
        SemanticFieldType.VOTING_APPROVED_PERCENT: "yes_percent",
        SemanticFieldType.VOTING_REJECTED_PERCENT: "no_percent",
    }
    for field in schema.fields:
        a = anchors[field.anchor_id]
        block = blocks[a.block_id]
        line = block.raw_text.casefold()
        label = field.raw_label.casefold().strip(" :,")
        scalar_key = scalar_types.get(field.semantic_type)
        clock = "end" if "kết thúc" in line else "start" if "hôm nay" in line else None
        if clock:
            if "ngày" in label:
                scalar_key = "end_day" if clock == "end" else "day"
            elif "tháng" in label:
                scalar_key = "end_month" if clock == "end" else "month"
            elif label == "năm":
                scalar_key = "end_year" if clock == "end" else "year"
            elif label == "giờ":
                scalar_key = clock + "_minute"
            elif "lúc" in label:
                scalar_key = clock + "_hour"
        if "phiếu, chiếm" in label or ("chiếm" in label and "%" in line):
            scalar_key = "no_percent" if "không tán thành" in line else "yes_percent"
        if a.placeholder_type == PlaceholderType.SIGNATURE_BLOCK:
            facts[field.field_id] = MeetingFact(
                field_id=field.field_id, reason="Giữ nguyên vùng chữ ký."
            )
            continue
        if scalar_key:
            if scalar_key in values:
                scalar_value, turn = values[scalar_key]
                facts[field.field_id] = MeetingFact(
                    field_id=field.field_id,
                    value=scalar_value,
                    status=FactStatus.NEEDS_REVIEW if turn.needs_review else FactStatus.SUPPORTED,
                    reason="Chuẩn hóa dữ kiện nêu rõ trong transcript; kiểm tra lại bản nháp.",
                    evidence_refs=[
                        EvidenceRef(
                            run_id=run_id,
                            turn_id=turn.turn_id,
                            source_id=turn.source_id,
                            start_sec=turn.start_sec,
                            end_sec=turn.end_sec,
                            text_snippet=turn.text,
                        )
                    ],
                )
            else:
                facts[field.field_id] = MeetingFact(
                    field_id=field.field_id, reason="Chưa có dữ kiện rõ để chuẩn hóa."
                )
        elif field.semantic_type in {
            SemanticFieldType.DOCUMENT_DATE_PLACE,
            SemanticFieldType.DOCUMENT_NUMBER,
            SemanticFieldType.PERSON_ROLE,
        }:
            facts[field.field_id] = MeetingFact(
                field_id=field.field_id,
                reason="Không suy ra ngày ban hành hay chức vụ từ ngày/vai trò cuộc họp.",
            )
    # 'Other attendees' excludes the explicitly recorded chair and secretary.
    role_names = {
        str(f.value).casefold()
        for f in facts.values()
        if f.field_id in {"chairperson_name", "secretary_name"} and f.value
    }
    seen_attendees = set()
    for field in schema.fields:
        if field.semantic_type == SemanticFieldType.ATTENDEE_LIST:
            fact = facts[field.field_id]
            attendee_key = (field.raw_label, field.section)
            if attendee_key in seen_attendees:
                fact.value, fact.status = "", FactStatus.SUPPORTED
            else:
                seen_attendees.add(attendee_key)
                if "khác" in field.raw_label.casefold() and isinstance(fact.value, list):
                    fact.value = [
                        name for name in fact.value if str(name).casefold() not in role_names
                    ]
    return list(facts.values())
