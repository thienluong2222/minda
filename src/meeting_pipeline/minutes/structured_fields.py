"""Conservative Vietnamese metadata normalization independent of generated prose."""

from __future__ import annotations

import re
from datetime import date
from itertools import pairwise
from typing import Any

from meeting_pipeline.minutes.evidence_retrieval import IndexedTurn
from meeting_pipeline.minutes.fact_extractor import M2RuleFactExtractor, stated_people
from meeting_pipeline.minutes.schemas import (
    DocGraph,
    FactStatus,
    MeetingFact,
    PlaceholderType,
    SemanticFieldType,
    TemplateField,
    TemplateSchema,
)
from meeting_pipeline.minutes.transcript_context import context_spans, evidence_refs

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
NUM_WORD = (
    r"(?:không|một|hai|ba|bốn|tư|năm|lăm|sáu|bảy|tám|chín|mười|mươi|trăm|"
    r"nghìn|ngàn|triệu|linh|lẻ)"
)
PHRASE = rf"(?:\d+|{NUM_WORD}(?:\s+{NUM_WORD})*)"


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
    for index, token in enumerate(tokens):
        if token in WORDS:
            # Preserve consecutive dictated digits after a scale as well:
            # "hai nghìn không trăm hai sáu" carries 26, not just its last 6.
            current = (
                current * 10 + WORDS[token]
                if index and tokens[index - 1] in WORDS
                else WORDS[token]
            )
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


VOTE_KEYS = {
    SemanticFieldType.VOTING_TOTAL: "vote_total",
    SemanticFieldType.VOTING_APPROVED_COUNT: "vote_yes",
    SemanticFieldType.VOTING_REJECTED_COUNT: "vote_no",
    SemanticFieldType.VOTING_APPROVED_PERCENT: "yes_percent",
    SemanticFieldType.VOTING_REJECTED_PERCENT: "no_percent",
}
DATE = re.compile(rf"ngày\s+({PHRASE})\s+tháng\s+({PHRASE})\s+năm\s+({PHRASE})")
DIGITAL_DATE = re.compile(r"(?:ngày\s+)?(\d{1,2})[/-](\d{1,2})[/-](\d{4})")
CLOCK = re.compile(
    rf"(?<!\w)(?:(\d{{1,2}})[:h](\d{{2}})|({PHRASE})\s*giờ"
    rf"(?:\s+(rưỡi|{PHRASE})(?:\s+phút)?)?)(?!\w)"
)
END = re.compile(r"\b(?:kết thúc|bế mạc|khép lại)\b")
MEETING = re.compile(r"\b(?:(?:toàn bộ |toàn thể )?cuộc họp|hội nghị)\b")
PART = re.compile(
    r"\b(?:phiên|phần|nội dung|mục|tiết|giải lao|nghỉ|chương trình|báo cáo|"
    r"biểu quyết|thảo luận|trình bày|bài phát biểu|ngày làm việc)\b"
)
UNCERTAIN = re.compile(
    r"\b(?:dự kiến|kế hoạch|đề xuất|nếu|có thể|sẽ|chưa|không|dời|"
    r"hoãn|khoảng|tạm|xin hỏi|phải không)\b"
)
VOTE_PATTERNS = {
    "vote_total": re.compile(rf"\btổng số\s+({PHRASE})\s+phiếu\b"),
    "vote_yes": re.compile(rf"\b({PHRASE})\s+phiếu tán thành\b"),
    "vote_no": re.compile(rf"\b({PHRASE})\s+phiếu không tán thành\b"),
    "abstain": re.compile(rf"\b({PHRASE})\s+phiếu (?:trắng|không ý kiến|không hợp lệ)\b"),
}
VOTE_SCOPE = re.compile(r"\b(?:nội dung|phương án|vấn đề|đề mục|lượt|vòng|lần)\s+")
VOTE_UNCERTAIN = re.compile(r"\b(?:dự kiến|giả sử|ước tính|nếu|chưa kiểm phiếu)\b")
CLAUSE_BOUNDARY = re.compile(r"[.!?;\n]+|,\s*(?=(?:sau đó|còn|riêng|toàn bộ|cuộc họp)\b)")


def clock_value(match, context: str) -> tuple[int, int]:
    h, m, hw, mw = match.groups()
    hour = int(h) if h is not None else vietnamese_number(hw)
    minute = int(m) if m is not None else 30 if mw == "rưỡi" else vietnamese_number(mw) if mw else 0
    if re.search(r"\b(?:chiều|tối)\b", context) and hour < 12:
        hour += 12
    return hour, minute


def _non_numeric_context(text: str) -> str:
    context = DATE.sub("", DIGITAL_DATE.sub("", CLOCK.sub("", text)))
    # Zero inside a spoken room/code ("hai không một") is not a negation.
    # A standalone "không" remains available to reject negative statements.
    return re.sub(
        rf"\b{PHRASE}\b",
        lambda match: "" if len(match.group().split()) > 1 else match.group(),
        context,
    )


def meeting_end_candidates(text: str):
    """Yield explicit whole-meeting closures and standalone closing announcements."""
    for clause in CLAUSE_BOUNDARY.split(text):
        for end in END.finditer(clause):
            prefix = clause[: end.start()]
            tail = clause[end.end() :]
            time = re.search(r"(?:lúc|vào)\s+(?:(?:vào|lúc)\s+)*(.+)", tail)
            time = CLOCK.match(time.group(1)) if time else CLOCK.match(tail.strip())
            subject = re.split(r"[,\u2013—]", prefix)[-1]
            scope = subject + " " + (tail[: time.start()] if time else tail)
            # The meeting may occur before or after the closing verb.
            if MEETING.search(tail.split("lúc")[0]):
                scope += " cuộc họp"
            statement = _non_numeric_context(clause)
            if not time or UNCERTAIN.search(statement) or text.strip().endswith("?"):
                continue
            explicit = bool(MEETING.search(scope)) and not PART.search(scope)
            if not explicit and prefix.strip(" ,:\u2013—") not in {"", "tuyên bố", "xin"}:
                continue
            hour, minute = clock_value(time, tail)
            if hour >= 24 or minute >= 60:
                continue
            explicit_date = DATE.search(tail) or DIGITAL_DATE.search(tail)
            closing_date = None
            if explicit_date:
                try:
                    day, month, year = map(vietnamese_number, explicit_date.groups())
                    closing_date = date(year, month, day)
                except ValueError:
                    pass
            yield explicit, hour, minute, closing_date, "cùng ngày" in tail


def _record_fact(
    key: str,
    value: Any,
    sources: list[IndexedTurn],
    run_id: str,
    *,
    reason: str | None = None,
    status: FactStatus | None = None,
) -> MeetingFact:
    return MeetingFact(
        field_id=key,
        value=value,
        status=status
        or (
            FactStatus.NEEDS_REVIEW
            if any(t.needs_review for t in sources)
            else FactStatus.SUPPORTED
        ),
        evidence_refs=evidence_refs(sources, run_id),
        reason=reason or "Dữ kiện nêu trong transcript; giữ các đoạn nguồn để đối chiếu.",
    )


def vote_records(turns: list[IndexedTurn], run_id: str) -> list[dict[str, MeetingFact]]:
    """Keep partial tallies and all evidence within a single identified round."""
    rounds = []
    current = None
    previous_end = None
    previous_span = None
    pending_scope = None
    positions = {turn.turn_id: index for index, turn in enumerate(turns)}
    barriers = {
        index
        for index, turn in enumerate(turns)
        if not turn.text.strip() or turn.asr_status not in {"transcribed", "user_edited"}
    }
    for span in context_spans(turns):
        first, last = span.turns[0], span.turns[-1]
        if previous_span is not None and (
            first.clock_id != previous_span.clock_id
            or first.session_id != previous_span.session_id
            or first.start_sec < previous_span.end_sec - 0.05
            or any(
                positions[previous_span.turn_id] < index < positions[first.turn_id]
                for index in barriers
            )
        ):
            current, pending_scope, previous_end = None, None, None
        previous_span = last
        text = span.text.casefold()
        # Every explicit issue/round starts a new scope, even within one ASR turn.
        markers = list(VOTE_SCOPE.finditer(text))
        boundaries = [0, *(m.start() for m in markers if m.start() > 0), len(text)]
        for left, right in pairwise(boundaries):
            chunk = text[left:right]
            sources = span.sources(left, right)
            scope = VOTE_SCOPE.search(chunk)
            if scope:
                current, pending_scope = None, None
                scope_name = re.search(
                    r"((?:nội dung|phương án|vấn đề|đề mục|lượt|vòng|lần)\s+.+?)"
                    r"(?=\s+(?:có|tổng số|kết quả)|[:,.;!?]|$)",
                    chunk,
                )
                if scope_name:
                    pending_scope = _record_fact(
                        "vote_scope", scope_name.group(1).strip(), sources, run_id
                    )
            matches = {
                key: [vietnamese_number(m.group(1)) for m in pattern.finditer(chunk)]
                for key, pattern in VOTE_PATTERNS.items()
            }
            matches["vote_no"].extend(
                0 for _ in re.finditer(r"không có phiếu không tán thành", chunk)
            )
            percent = re.search(rf"tỷ lệ tán thành (?:là )?({PHRASE}) (?:phần\s+)+trăm", chunk)
            if percent:
                matches["yes_percent"] = [vietnamese_number(percent.group(1))]
            if VOTE_UNCERTAIN.search(chunk):
                current, pending_scope, previous_end = None, None, None
                continue
            if not any(matches.values()):
                continue
            if (
                pending_scope
                and sources[0].start_sec - pending_scope.evidence_refs[-1].end_sec > 10
            ):
                pending_scope = None
            fresh = (
                current is None
                or scope is not None
                or (previous_end is not None and sources[0].start_sec - previous_end > 10)
                or any(
                    key in current and current[key].value != counts[0]
                    for key, counts in matches.items()
                    if counts and key == "vote_total"
                )
            )
            if fresh:
                current = {}
                if pending_scope:
                    current["vote_scope"] = pending_scope
                    pending_scope = None
                rounds.append(current)
            for key, counts in matches.items():
                for count in counts:
                    existing = current.get(key)
                    if existing and existing.value != str(count):
                        current[key] = _record_fact(
                            key,
                            None,
                            sources,
                            run_id,
                            status=FactStatus.CONFLICTING,
                            reason="Có số liệu khác nhau trong cùng lượt; cần xác nhận lại.",
                        )
                    elif not existing:
                        current[key] = _record_fact(key, str(count), sources, run_id)
            previous_end = sources[-1].end_sec
    for result in rounds:
        counts = {
            key: int(f.value)
            for key, f in result.items()
            if f.value is not None and key != "vote_scope"
        }
        total, yes, no = (counts.get(key) for key in ("vote_total", "vote_yes", "vote_no"))
        if total is not None and yes is not None and no is not None:
            if yes + no + counts.get("abstain", 0) != total:
                for fact in result.values():
                    fact.status = FactStatus.CONFLICTING
                    fact.value = None
                    fact.reason = "Tổng các loại phiếu không khớp tổng số; cần đối chiếu."
                continue
        if total is None or total <= 0:
            continue
        for key, percent_key in (("vote_yes", "yes_percent"), ("vote_no", "no_percent")):
            if key not in counts:
                continue
            if not 0 <= counts[key] <= total:
                result[key].status, result[key].value = FactStatus.CONFLICTING, None
                continue
            value = f"{100 * counts[key] / total:g}"
            if percent_key in result:
                if result[percent_key].value != value:
                    result[percent_key].status, result[percent_key].value = (
                        FactStatus.CONFLICTING,
                        None,
                    )
            else:
                fact = result[key].model_copy(deep=True)
                fact.field_id, fact.value = percent_key, value
                fact.reason = "Tỷ lệ tính từ số phiếu và tổng số của cùng lượt biểu quyết."
                fact.evidence_refs = list(
                    {
                        (ref.run_id, ref.turn_id): ref
                        for ref in [*fact.evidence_refs, *result["vote_total"].evidence_refs]
                    }.values()
                )
                result[percent_key] = fact
    return rounds


def voting_values(valid: list[IndexedTurn]) -> dict[str, tuple[str, IndexedTurn]]:
    rounds = vote_records(valid, "rules")
    by_id = {turn.turn_id: turn for turn in valid}
    if len(rounds) != 1:
        return {}
    return {
        key: (str(fact.value), by_id[fact.evidence_refs[0].turn_id])
        for key, fact in rounds[0].items()
        if fact.value is not None
    }


def scoped_scalar_key(field: TemplateField, line: str, label: str) -> str | None:
    if "phiếu, chiếm" in label or ("chiếm" in label and "%" in line):
        return "no_percent" if "không tán thành" in line else "yes_percent"
    if field.semantic_type in VOTE_KEYS:
        return VOTE_KEYS[field.semantic_type]
    if label == "tổng số" and re.search(r"\btổng số\s+[.…]+\s+phiếu\b", line):
        return "vote_total"
    kind = (
        "end"
        if END.search(line) or field.semantic_type == SemanticFieldType.MEETING_END_TIME
        else "start"
        if re.search(r"hôm nay|bắt đầu|khai mạc|thời gian", line)
        or field.semantic_type == SemanticFieldType.MEETING_START_TIME
        else None
    )
    if kind:
        for word, key in (("ngày", "day"), ("tháng", "month"), ("năm", "year")):
            if word in label and (word != "năm" or label == "năm"):
                return ("end_" if kind == "end" else "") + key
        slots = len(re.findall(r"[.…]{2,}|_{3,}", line))
        if slots > 1:
            if label in {"giờ", "phút"}:
                return kind + "_minute"
            if re.search(r"lúc|giờ|thời gian", label):
                return kind + "_hour"
        return kind + "_time"
    if field.semantic_type == SemanticFieldType.MEETING_LOCATION:
        return "location"
    if field.semantic_type in {
        SemanticFieldType.MEETING_TOPIC,
        SemanticFieldType.MEETING_AGENDA_SUMMARY,
    }:
        return "topic"
    if field.semantic_type == SemanticFieldType.PERSON_NAME:
        if re.search(r"chủ trì|chủ tọa", label):
            return "chairperson_name"
        if re.search(r"thư ký|người ghi biên bản", label):
            return "secretary_name"
    return None


def scoped_field_ids(schema: TemplateSchema, graph: DocGraph) -> set[str]:
    """Fields whose values must come from the scoped clock and vote rules."""
    anchors = {a.anchor_id: a for a in graph.all_anchors}
    blocks = {b.block_id: b for b in graph.blocks}
    return {
        field.field_id
        for field in schema.fields
        if scoped_scalar_key(
            field,
            blocks[anchors[field.anchor_id].block_id].raw_text.casefold(),
            field.raw_label.casefold().strip(" :,"),
        )
    }


def extract_meeting_record(
    turns: list[IndexedTurn],
    run_id: str,
) -> tuple[dict[str, MeetingFact], list[dict[str, MeetingFact]]]:
    """Template-independent values and evidence, including partially known results."""
    values: dict[str, tuple[str, IndexedTurn]] = {}
    sources_by_key: dict[str, list[IndexedTurn]] = {}
    spans = context_spans(turns)
    for span in spans:
        turn = span.turns[0]
        text = span.text.casefold()
        for clause in CLAUSE_BOUNDARY.split(text):
            if END.search(clause):
                continue
            opening = re.search(
                r"(?:cuộc họp|hội nghị).{0,20}(?:bắt đầu|khai mạc|diễn ra)|"
                r"(?:bắt đầu|khai mạc).{0,12}(?:cuộc họp|hội nghị)|hôm nay",
                clause,
            )
            # Dates mentioned as task deadlines must not become the meeting date.
            calendar_context = opening or re.match(r"\s*ngày\b", clause)
            for match in sorted(
                [*DATE.finditer(clause), *DIGITAL_DATE.finditer(clause)], key=lambda m: m.start()
            ):
                if not calendar_context:
                    continue
                try:
                    d, m, y = (vietnamese_number(s) for s in match.groups())
                    date(y, m, d)
                    for key, value in (("day", d), ("month", m), ("year", y)):
                        if key == "year" and re.search(
                            r"\b(?:không|linh|lẻ|mươi)$", match.group(3)
                        ):
                            continue
                        if key not in values:
                            values[key] = str(value), turn
                            sources_by_key[key] = span.sources(match.start(), match.end())
                except ValueError:
                    pass
            time_match = CLOCK.search(clause)
            factual_context = _non_numeric_context(clause)
            if time_match and opening and not UNCERTAIN.search(factual_context):
                h, minute = clock_value(time_match, clause)
                if h < 24 and minute < 60:
                    values.setdefault("start_hour", (str(h), turn))
                    values.setdefault("start_minute", (f"{minute:02d}", turn))
                    sources_by_key.setdefault("start_hour", span.sources())
                    sources_by_key.setdefault("start_minute", span.sources())
        location = re.search(r"\btại\s+([^.!?]+)", span.text, re.IGNORECASE)
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
            sources_by_key.setdefault("location", span.sources())
        topic = re.search(
            r"\b(?:về việc|vì việc|với chủ đề|chủ đề(?: cuộc họp)?(?: là)?|"
            r"nội dung(?: cuộc họp)?(?: là)?)\s+([^.!?]+)",
            span.text,
            re.IGNORECASE,
        )
        if topic:
            values.setdefault("topic", (topic.group(1).strip(), turn))
            sources_by_key.setdefault("topic", span.sources())
    closing = [
        (candidate, turn)
        for span in spans
        for turn in [span.turns[0]]
        for candidate in meeting_end_candidates(span.text.casefold())
    ]
    explicit = [entry for entry in closing if entry[0][0]]
    preferred = explicit or closing
    times = {(candidate[1], candidate[2]) for candidate, _ in preferred}
    if len(times) == 1:
        (_, hour, minute, _, _), turn = next(
            (entry for entry in preferred if not entry[1].needs_review), preferred[0]
        )
        values.update(
            end_time=(f"{hour:02d}:{minute:02d}", turn),
            end_hour=(str(hour), turn),
            end_minute=(f"{minute:02d}", turn),
        )
        closing_dates = {
            ending: source for (_, _, _, ending, _), source in preferred if ending is not None
        }
        if len(closing_dates) == 1:
            ending, source = next(iter(closing_dates.items()))
            for key in ("day", "month", "year"):
                values["end_" + key] = str(getattr(ending, key)), source
        elif not closing_dates and any(candidate[4] for candidate, _ in preferred):
            for key in ("day", "month", "year"):
                if key in values:
                    values["end_" + key] = values[key]
    for key in ("end_time", "end_hour", "end_minute"):
        if key in values:
            sources_by_key[key] = next(
                span.sources() for span in spans if span.turns[0].turn_id == values[key][1].turn_id
            )
    for key in ("day", "month", "year"):
        if "end_" + key in values:
            source = values["end_" + key][1]
            if key in values and source.turn_id == values[key][1].turn_id:
                sources_by_key["end_" + key] = [
                    *sources_by_key.get(key, [source]),
                    *sources_by_key.get("end_hour", []),
                ]
            else:
                sources_by_key["end_" + key] = next(
                    span.sources() for span in spans if span.turns[0].turn_id == source.turn_id
                )
    if "start_hour" in values:
        hour, source = values["start_hour"]
        minute = values.get("start_minute", ("00", source))[0]
        values["start_time"] = f"{int(hour):02d}:{minute}", source
        sources_by_key["start_time"] = sources_by_key["start_hour"]
    record = {
        key: _record_fact(key, value, sources_by_key.get(key, [turn]), run_id)
        for key, (value, turn) in values.items()
    }
    rounds = vote_records(turns, run_id)
    if len(rounds) == 1:
        record.update(rounds[0])
    people = stated_people(turns)
    for role, key in (("chair", "chairperson_name"), ("secretary", "secretary_name")):
        named = people[role]
        if len(named) == 1:
            name, sources = next(iter(named.items()))
            record[key] = _record_fact(key, name, sources, run_id)
        elif named:
            record[key] = _record_fact(
                key,
                None,
                [t for sources in named.values() for t in sources],
                run_id,
                status=FactStatus.CONFLICTING,
                reason="Có nhiều tên được nêu cho cùng vai trò.",
            )
    return record, rounds


def structured_facts(
    schema: TemplateSchema,
    graph: DocGraph,
    turns: list[IndexedTurn],
    run_id: str,
    meeting_metadata: dict[str, Any] | None = None,
    *,
    scoped_only: bool = False,
) -> list[MeetingFact]:
    baseline = M2RuleFactExtractor().extract_facts(schema, turns, meeting_metadata, run_id)
    facts = {f.field_id: f for f in baseline}
    anchors = {a.anchor_id: a for a in graph.all_anchors}
    blocks = {b.block_id: b for b in graph.blocks}
    record, rounds = extract_meeting_record(turns, run_id)
    scalar_types = {
        SemanticFieldType.MEETING_LOCATION: "location",
        SemanticFieldType.MEETING_TOPIC: "topic",
        SemanticFieldType.MEETING_AGENDA_SUMMARY: "topic",
    }
    for field in schema.fields:
        a = anchors[field.anchor_id]
        block = blocks[a.block_id]
        line = block.raw_text.casefold()
        label = field.raw_label.casefold().strip(" :,")
        if a.placeholder_type == PlaceholderType.FIXED_TEXT:
            unsigned = [
                t
                for t in turns
                if re.search(
                    r"chữ ký.{0,35}chưa|(?:chưa|chưa có ai)\s+ký|ký\s+sau|sẽ\s+ký", t.text, re.I
                )
            ]
            facts[field.field_id] = (
                _record_fact(
                    field.field_id,
                    a.placeholder_text,
                    unsigned,
                    run_id,
                    status=FactStatus.CONFLICTING,
                    reason="Mẫu xác nhận đã ký, nhưng lời chép nói chưa ký. "
                    "Hãy sửa câu trong mẫu hoặc xác nhận lại tình trạng ký.",
                )
                if unsigned
                else MeetingFact(field_id=field.field_id)
            )
            continue
        scalar_key = scoped_scalar_key(field, line, label)
        if scoped_only and scalar_key is None:
            continue
        if scalar_key is None:
            scalar_key = scalar_types.get(field.semantic_type)
            if "hôm nay" in line:
                if "ngày" in label:
                    scalar_key = "day"
                elif "tháng" in label:
                    scalar_key = "month"
                elif label == "năm":
                    scalar_key = "year"
                elif label == "giờ":
                    scalar_key = "start_minute"
                elif "lúc" in label:
                    scalar_key = "start_hour"
        if a.placeholder_type == PlaceholderType.SIGNATURE_BLOCK:
            facts[field.field_id] = MeetingFact(
                field_id=field.field_id, reason="Giữ nguyên vùng chữ ký."
            )
            continue
        if scalar_key:
            field_record = record
            if scalar_key in VOTE_KEYS.values() and len(rounds) > 1:
                context = (field.section + " " + field.raw_label).casefold()
                matches = [
                    group
                    for group in rounds
                    if group.get("vote_scope")
                    and str(group["vote_scope"].value).casefold() in context
                ]
                field_record = matches[0] if len(matches) == 1 else {}
            if any(
                ref.source_kind == "meeting_metadata" for ref in facts[field.field_id].evidence_refs
            ):
                continue
            if scalar_key in field_record:
                facts[field.field_id] = field_record[scalar_key].model_copy(
                    update={"field_id": field.field_id}, deep=True
                )
            elif (
                scalar_key not in {"chairperson_name", "secretary_name"}
                or facts[field.field_id].value is None
            ):
                facts[field.field_id] = MeetingFact(
                    field_id=field.field_id,
                    reason=(
                        "Chưa xác định được một kết quả biểu quyết đầy đủ cho trường này."
                        if scalar_key in VOTE_KEYS.values()
                        else "Chưa có dữ kiện rõ để chuẩn hóa."
                    ),
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
    if scoped_only:
        return list(facts.values())
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
