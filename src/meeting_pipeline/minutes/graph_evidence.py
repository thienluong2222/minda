"""Ground event attributes and relations in character spans of the raw transcript."""

from __future__ import annotations

import re

from meeting_pipeline.minutes.graph_contracts import FACT_FIELDS, Event, EvidenceAnchor, GraphUnit
from meeting_pipeline.minutes.graph_values import canonical_values

SELF_ASSIGNMENT = re.compile(r"\btôi\s+(?:(?:cũng|xin)\s+)?(?:nhận|sẽ|phụ trách|thực hiện)\b", re.I)
DEADLINE_CHANGE = re.compile(
    r"\b(?:đổi|chuyển|dời|lùi|sửa|điều chỉnh)\b[^;.!?]*?\btừ\b[^;.!?]+?"
    r"\b(?:sang|thành|đến)\s+",
    re.I,
)
ASSIGNMENT_CUE = re.compile(r"(?<!được )\b(?:giao(?:\s+cho)?|phân công(?:\s+cho)?)\s+", re.I)
CONDITIONAL_CUE = re.compile(
    r"\b(?:nếu|khi|với điều kiện|điều kiện là|trong trường hợp|miễn là|tùy|chờ|phụ thuộc)\b",
    re.I,
)


def quote_anchor(
    unit: GraphUnit, quote: str, within: EvidenceAnchor | None = None
) -> EvidenceAnchor | None:
    if not quote.strip():
        return None
    left, right = (within.start_char, within.end_char) if within else (0, len(unit.original))
    match = re.search(rf"(?<!\w){re.escape(quote)}(?!\w)", unit.original[left:right], re.I)
    if match is None:
        return None
    return EvidenceAnchor(
        unit_id=unit.unit_id,
        start_char=left + match.start(),
        end_char=left + match.end(),
        quote=match.group(),
    )


def anchor_valid(anchor: EvidenceAnchor, units: dict[str, GraphUnit]) -> bool:
    unit = units.get(anchor.unit_id)
    return bool(
        unit
        and anchor.end_char <= len(unit.original)
        and unit.original[anchor.start_char : anchor.end_char] == anchor.quote
    )


def ground_event(event: Event, unit: GraphUnit) -> Event:
    """Use the event clause, then bind the value to a span of the same raw source."""
    event.anchor = quote_anchor(unit, event.text)
    if event.anchor is None and event.text == unit.text:
        event.anchor = quote_anchor(unit, unit.original)
    event.field_evidence = {}
    for field in FACT_FIELDS:
        value = getattr(event, field)
        if not value:
            continue
        found = re.search(rf"(?<!\w){re.escape(value)}(?!\w)", event.text, re.I)
        anchor = quote_anchor(unit, value, event.anchor) if found and event.anchor else None
        if field == "owner":
            speaker = re.split(r"\s+[\u2014\u2013]\s+", unit.speaker, maxsplit=1)[0].strip()
            self_assignment = SELF_ASSIGNMENT.search(event.text)
            if (
                not anchor
                and self_assignment
                and event.anchor
                and value.casefold() == speaker.casefold()
                and not re.match(r"người lạ|chưa xác định|speaker|unknown", speaker, re.I)
            ):
                anchor = quote_anchor(unit, self_assignment.group(), event.anchor)
                if anchor:
                    anchor.method = "speaker_self_reference"
            assignment = ASSIGNMENT_CUE.search(event.text)
            if found and assignment and found.start() < assignment.end():
                # A named speaker in "Lan giao Minh..." is not the recipient.
                anchor = None
            if re.search(
                rf"\b\w+\s+và\s+{re.escape(value)}\b|\b{re.escape(value)}\s+và\s+\w+\b",
                event.text,
                re.I,
            ):
                event.warnings.append("multiple_actors_require_separate_facts")
                anchor = None
        if field == "deadline" and found:
            change = DEADLINE_CHANGE.search(event.text)
            if change and found.start() < change.end():
                # The first date in "đổi từ ... sang ..." describes the previous state.
                anchor = None
        if field == "condition" and found and not CONDITIONAL_CUE.search(event.text[: found.end()]):
            anchor = None
        if anchor:
            event.field_evidence[field] = anchor
        else:
            setattr(event, field, None)
            event.warnings.append(f"unsupported_{field}")
    event.warnings = list(dict.fromkeys(event.warnings))
    return event


def date_values(text: str) -> set[tuple]:
    return {value for category, value, _ in canonical_values(text) if category == "date"}
