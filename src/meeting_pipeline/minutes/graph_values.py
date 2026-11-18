"""Shared numeric representation for graph verification, reused from the existing fact guards.

Dates, clocks and quantities may change surface spelling but not value or unit.
This module deliberately does not treat a matching number as semantic entailment.
"""

from __future__ import annotations

import re
from collections import Counter

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


DATE = re.compile(rf"ngày\s+({PHRASE})\s+tháng\s+({PHRASE})\s+năm\s+({PHRASE})")

CLOCK = re.compile(
    rf"(?<!\w)(?:(\d{{1,2}})[:h](\d{{2}})|({PHRASE})\s*giờ"
    rf"(?:\s+(rưỡi|{PHRASE})(?:\s+phút)?)?)(?!\w)"
)

QUANTITY = re.compile(
    rf"\b({PHRASE})(?:\s+(tài liệu|hồ sơ|phiếu|người|thành viên|đồng|triệu đồng|"
    r"phần trăm)|\s*(%))(?=\s|[.,;!?]|$)",
    re.I,
)

PARTIAL_DATE = re.compile(rf"\bngày\s+({PHRASE})\s+tháng\s+({PHRASE})", re.I)

DIGITAL_DATE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{4}))?\b")


def canonical_values(text: str) -> Counter:
    """Compare Vietnamese word/digit values independently of actor and state checks."""
    lower = text.casefold()
    claims = Counter()
    occupied = set()
    # Protect the full identifier, not only its digits (B201 must not become C201).
    for match in re.finditer(r"\b([a-zđ]{1,5}\d{2,8})\b", lower):
        claims[("identifier", match.group(1), "")] += 1
        occupied.update(range(match.start(), match.end()))
    letters = {"a": "a", "bê": "b", "xê": "c", "đê": "d", "e": "e", "g": "g", "hát": "h"}
    for match in re.finditer(rf"\bphòng\s+(a|bê|xê|đê|e|g|hát)\s+({PHRASE})(?!\w)", lower):
        if any(i in occupied for i in range(match.start(), match.end())):
            continue
        try:
            code = letters[match.group(1)] + str(vietnamese_number(match.group(2)))
        except ValueError:
            continue
        claims[("identifier", code, "")] += 1
        occupied.update(range(match.start(), match.end()))
    # A voting ratio is not a calendar date. Preserve numerator polarity and total.
    for match in re.finditer(
        r"\b(\d+)\s*(?:/|trên)\s*(\d+)\s+phiếu\s+(không tán thành|tán thành)\b", lower
    ):
        numerator, total = int(match.group(1)), int(match.group(2))
        relation = "reject" if match.group(3).startswith("không") else "approve"
        claims[("quantity", (numerator, "phiếu"), relation)] += 1
        claims[("quantity", (total, "phiếu"), "")] += 1
        occupied.update(range(match.start(), match.end()))
    for match in re.finditer(r"không có phiếu\s+(không tán thành|tán thành|phản đối)", lower):
        relation = (
            "reject"
            if match.group(1).startswith("không") or match.group(1) == "phản đối"
            else "approve"
        )
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
                    unit = match.group(2) or match.group(3)
                    unit = {"thành viên": "người", "%": "phần trăm"}.get(unit, unit)
                    value = (vietnamese_number(match.group(1)), unit)
                relation = ""
                if category == "quantity" and value[1] == "phiếu":
                    polarity = re.match(
                        r"\s+(không tán thành|tán thành|phản đối)\b", lower[match.end() :]
                    )
                    if polarity:
                        relation = (
                            "reject"
                            if polarity.group(1).startswith("không")
                            or polarity.group(1) == "phản đối"
                            else "approve"
                        )
            except ValueError:
                continue
            claims[(category, value, relation)] += 1
            occupied.update(range(match.start(), match.end()))
    # Unclassified digit sequences are also protected, including codes and IDs.
    for match in re.finditer(r"\d+", lower):
        if not any(i in occupied for i in range(match.start(), match.end())):
            claims[("number", int(match.group()), "")] += 1
    return claims
