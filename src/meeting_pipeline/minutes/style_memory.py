"""Versioned, scoped style rules learned from confirmed edits, without weight training."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from meeting_pipeline.minutes.graph_contracts import StyleProfile, StyleRule, default_style, digest

LAYOUT_MARKER = re.compile(r"(?m)^[ \t]*(?:\d+[.)]|[-•])[ \t]+")


def scoped_instructions(
    profile: StyleProfile | None, section_id: str, roles: set[str]
) -> list[dict[str, str]]:
    if profile is None:
        return []
    scopes = {"general", section_id, *roles}
    if roles - {"task", "vote"}:
        scopes.add("discussion")
    return [
        {"scope": rule.scope, "instruction": rule.instruction}
        for rule in profile.rules
        if rule.active and rule.scope in scopes
    ]


def preserves_reviewed_claims(before: str, after: str, plan: dict) -> bool:
    """Automatically learn only layout edits with the reviewed claim surfaces intact."""

    def layout_text(text: str) -> str:
        return " ".join(LAYOUT_MARKER.sub("", text).split())

    normalized = layout_text(before)
    if plan.get("schema_version") != "3.0" or normalized != layout_text(after):
        return False
    paragraphs = [p for section in plan.get("sections", []) for p in section["paragraphs"]]
    if not paragraphs:
        return False
    for paragraph in paragraphs:
        text = paragraph["text"]
        alignments = paragraph.get("alignments", [])
        if paragraph["verification"] != "checked" or (
            set(paragraph["claim_ids"]) != {item["claim_id"] for item in alignments}
        ):
            return False
        for item in alignments:
            quote = layout_text(text[item["start_char"] : item["end_char"]])
            if not quote or quote not in normalized:
                return False
    return True


def learn_style_rules(
    profile: StyleProfile, edits: list[dict[str, Any]], *, minimum_support: int = 2
) -> tuple[StyleProfile, dict[str, Any]]:
    """Learn presentation signals only. Factual corrections never become style memory.

    `approved` is supplied by the review workflow, not by model-generated output.
    Independent edit IDs, rather than repeated review requests, count as support.
    """
    updated = profile.model_copy(deep=True)
    rules = {r.rule_id: r for r in updated.rules}
    audit: dict[str, Any] = {"accepted_edit_ids": [], "rejected": []}
    for edit in edits:
        before, after = str(edit.get("before", "")), str(edit.get("after", ""))
        edit_id = str(edit.get("edit_id") or digest([before, after]))
        if not edit.get("approved") or not edit.get("facts_unchanged") or not before or not after:
            audit["rejected"].append({"edit_id": edit_id, "reason": "unconfirmed_or_factual_edit"})
            continue

        def numbers(s: str) -> Counter:
            return Counter(re.findall(r"\d+(?:[.,:/-]\d+)*", LAYOUT_MARKER.sub("", s)))

        if numbers(before) != numbers(after):
            audit["rejected"].append({"edit_id": edit_id, "reason": "changed_numbers"})
            continue
        proposals = []
        if len(re.findall(r"(?:phát biểu|cho biết|nêu ý kiến|nói rằng)", before, re.I)) > len(
            re.findall(r"(?:phát biểu|cho biết|nêu ý kiến|nói rằng)", after, re.I)
        ):
            proposals.append(
                (
                    "reduce_reporting",
                    "Gộp ý liên quan thành đoạn; giảm các cụm dẫn lời lặp lại, "
                    "giữ chủ thể khi có trách nhiệm hoặc quan điểm khác nhau.",
                )
            )
        if len(re.findall(r"(?m)^\s*\d+[.)]\s", before)) > len(
            re.findall(r"(?m)^\s*\d+[.)]\s", after)
        ):
            proposals.append(
                (
                    "minimal_headings",
                    "Hạn chế đánh số và đề mục khi nội dung ngắn; "
                    "ưu tiên các đoạn văn nối tiếp rõ ràng.",
                )
            )
        names = list(edit.get("names", []))
        if any(
            before.casefold().count(n.casefold()) > after.casefold().count(n.casefold())
            for n in names
            if n
        ):
            proposals.append(
                (
                    "reduce_names",
                    "Giảm lặp tên khi chủ thể đã rõ; "
                    "giữ tên ở phân công, ý kiến bảo lưu và khi chuyển chủ thể.",
                )
            )
        if re.match(r"\s*(?:Cuộc họp|Các bên|Về\s|Đối với\s)", after) and not re.match(
            r"\s*(?:Cuộc họp|Các bên|Về\s|Đối với\s)", before
        ):
            proposals.append(
                (
                    "issue_lead",
                    "Mở đoạn bằng vấn đề hoặc kết quả đã có căn cứ, "
                    "sau đó trình bày diễn biến cần thiết; "
                    "giữ đề xuất và kết luận đúng trạng thái.",
                )
            )
        for key, instruction in proposals:
            rule_id = "learned_" + key
            rule = rules.get(rule_id) or StyleRule(rule_id=rule_id, instruction=instruction)
            refs = list(dict.fromkeys([*rule.source_edit_ids, edit_id]))
            rule.source_edit_ids = refs
            rule.support_count = len(refs)
            rule.active = len(refs) >= minimum_support
            rules[rule_id] = rule
        audit["accepted_edit_ids"].append(edit_id)
    updated.rules = list(rules.values())
    if updated.model_dump(exclude={"revision"}) != profile.model_dump(exclude={"revision"}):
        updated.revision += 1
    return updated, audit


def profile_from_metadata(metadata: dict[str, Any]) -> StyleProfile:
    data = metadata.get("style_profile")
    return StyleProfile.model_validate(data) if data else default_style()
