"""Compare typed values and their local predicates during narrative rewriting."""

from __future__ import annotations

import re
from collections import Counter

from meeting_pipeline.minutes.structured_fields import CLOCK, DATE, PHRASE, vietnamese_number

ACTIONS = {
    "gửi": "send",
    "nộp": "send",
    "chuyển": "send",
    "nhập": "enter",
    "hoàn tất": "complete",
    "hoàn thành": "complete",
    "kiểm tra": "check",
    "rà soát": "check",
    "đối chiếu": "check",
    "công bố": "publish",
    "ban hành": "issue",
    "chia": "organize",
    "tán thành": "approve",
    "chủ trì": "chair",
    "thư ký": "secretary",
}
ACTION = re.compile(r"\b(?:" + "|".join(sorted(ACTIONS, key=len, reverse=True)) + r")\b")
QUANTITY = re.compile(
    rf"\b({PHRASE})\s+(tài liệu|hồ sơ|phiếu|người|thành viên|đồng|triệu đồng|"
    r"phần trăm|%)(?=\s|[.,;!?]|$)",
    re.I,
)
PARTIAL_DATE = re.compile(rf"\bngày\s+({PHRASE})\s+tháng\s+({PHRASE})", re.I)
DIGITAL_DATE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{4}))?\b")
CLAUSE = re.compile(r"[.!?;]+|,\s*|\bvà\b")


def _predicate(text: str, offset: int) -> str:
    prefix = re.split(r"[.!?;]", text[:offset])[-1]
    actions = list(ACTION.finditer(prefix.casefold()))
    return ACTIONS[actions[-1].group()] if actions else ""


def numeric_claims(text: str) -> Counter:
    """Dates, clocks and quantities retain value, unit and associated action."""
    lower = text.casefold()
    claims = Counter()
    occupied = set()
    for match in re.finditer(r"không có phiếu\s+(không tán thành|tán thành)", lower):
        relation = "reject" if match.group(1).startswith("không") else "approve"
        claims[("quantity", (0, "phiếu"), relation)] += 1
        occupied.update(range(match.start(), match.end()))
    for category, pattern in (
        ("date", DATE),
        ("date", DIGITAL_DATE),
        ("date", PARTIAL_DATE),
        ("clock", CLOCK),
        ("quantity", QUANTITY),
    ):
        for match in pattern.finditer(lower):
            if any(i in occupied for i in range(match.start(), match.end())):
                continue
            try:
                if category == "date":
                    value = tuple(
                        vietnamese_number(g) if g is not None else None for g in match.groups()
                    )
                    value = value + (None,) * (3 - len(value))
                elif category == "clock":
                    h, m, hw, mw = match.groups()
                    value = (
                        int(h) if h is not None else vietnamese_number(hw),
                        int(m)
                        if m is not None
                        else 30
                        if mw == "rưỡi"
                        else vietnamese_number(mw)
                        if mw
                        else 0,
                    )
                else:
                    unit = match.group(2)
                    unit = {"thành viên": "người", "%": "phần trăm"}.get(unit, unit)
                    value = (vietnamese_number(match.group(1)), unit)
            except ValueError:
                continue
            claims[(category, value, _predicate(lower, match.start()))] += 1
            occupied.update(range(match.start(), match.end()))
    # Unclassified digit sequences are also protected, including codes and IDs.
    for match in re.finditer(r"\d+", lower):
        if not any(i in occupied for i in range(match.start(), match.end())):
            claims[("number", int(match.group()), _predicate(lower, match.start()))] += 1
    return claims


def _actors(text: str, names: set[str]) -> Counter:
    result = Counter()
    for clause in CLAUSE.split(text.casefold()):
        for name in names:
            for match in re.finditer(rf"\b{re.escape(name.casefold())}\b", clause):
                action = ACTION.search(clause[match.end() :])
                if action:
                    prefix = clause[match.end() : match.end() + action.start()]
                    state = "negative" if re.search(r"\b(?:không|chưa)\b", prefix) else "positive"
                    result[(name.casefold(), ACTIONS[action.group()], state)] += 1
    return result


def rewrite_risks(source: str, candidate: str, names: set[str]) -> list[str]:
    risks = []
    if numeric_claims(source) != numeric_claims(candidate):
        risks.append("changed_value_or_relation")
    coordinated = r"\b(\w+\s+và\s+\w+)\s+(?:thực hiện|gửi|nhập|kiểm tra|hoàn thành)\b"
    if re.findall(coordinated, source.casefold()) != re.findall(coordinated, candidate.casefold()):
        risks.append("changed_coordinated_actor")
    if _actors(source, names) != _actors(candidate, names):
        risks.append("changed_actor_or_action")
    for name in names:
        pattern = rf"\b{re.escape(name.casefold())}\b"
        if bool(re.search(pattern, source.casefold())) != bool(
            re.search(pattern, candidate.casefold())
        ):
            risks.append("changed_named_person")
            break
    for pattern in (
        r"\b(?:không|chưa)\b",
        r"\b(?:nếu|chỉ khi|trừ khi)\b",
        r"\b(?:đề xuất|đề nghị|kiến nghị)\b",
        r"\b(?:rút|hủy|bác bỏ)\b",
        r"\b(?:có thể|dự kiến|ước tính|tạm)\b",
        r"\b(?:thống nhất|quyết định|thông qua|kết luận)\b",
    ):
        if bool(re.search(pattern, source.casefold())) != bool(
            re.search(pattern, candidate.casefold())
        ):
            risks.append("changed_statement_state")
    if re.search(r"\bđã\b", candidate.casefold()) and not re.search(r"\bđã\b", source.casefold()):
        risks.append("added_completion")
    if "cam kết" in candidate.casefold() and "cam kết" not in source.casefold():
        risks.append("added_commitment")
    return risks


def statement_kind(text: str) -> str:
    lower = text.casefold()
    if re.search(r"kết thúc|bế mạc|chữ ký|ký sau", lower):
        return "closing"
    if re.search(r"tổng số.*phiếu|phiếu tán thành|^kết quả biểu quyết", lower):
        return "voting"
    if re.search(
        r"tôi kết luận|quyết định|thống nhất như sau|đã thông qua|"
        r"đọc lại.*biên bản|xác nhận biên bản",
        lower,
    ):
        return "decision"
    if re.search(r"bắt đầu cuộc họp|hôm nay.*(?:lúc|ngày)|khai mạc|tại phòng", lower):
        return "opening"
    if re.search(r"thành phần|tham dự|dự họp|dự học|làm thư ký", lower):
        return "participants"
    return "discussion"


def is_fragment(text: str) -> bool:
    words = re.findall(r"\w+", text)
    return len(words) <= 3 and not re.search(
        r"đồng ý|nhất trí|tán thành|không đồng ý|xin cảm ơn|kết thúc", text, re.I
    )


def safe_sentence(text: str) -> str:
    text = text.strip()
    return text[:1].upper() + text[1:] + ("" if re.search(r"[.!?]$", text) else ".")
