"""Validate the source links of individual assertions and check slot bindings."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from meeting_pipeline.minutes.graph_contracts import INACTIVE_STATES, ClaimAlignment, Paragraph
from meeting_pipeline.minutes.graph_evidence import CONDITIONAL_CUE, date_values

SENTENCE = re.compile(r"[^\n;]+?(?:[.!?](?=\s|$)|(?=[;\n]|$))")
DEADLINE_CUE = re.compile(r"\b(?:hạn|trước|chậm nhất|hoàn thành vào|nộp vào)\b", re.I)


def named(text: str, name: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.I))


def assertion_fragments(text: str) -> list[re.Match]:
    return [match for match in SENTENCE.finditer(text) if any(c.isalnum() for c in match.group())]


def deadline_binding_risks(text: str, claims: list[dict]) -> list[str]:
    dates_by_owner: dict[str, set[tuple]] = {}
    for claim in claims:
        if (
            claim.get("owner")
            and claim.get("deadline")
            and claim.get("lifecycle") not in INACTIVE_STATES
        ):
            dates_by_owner.setdefault(claim["owner"], set()).update(date_values(claim["deadline"]))
    risks = []
    for match in SENTENCE.finditer(text):
        fragment = match.group()
        owners = [name for name in dates_by_owner if named(fragment, name)]
        if len(owners) == 1 and DEADLINE_CUE.search(fragment):
            expected = dates_by_owner[owners[0]]
            observed = date_values(fragment)
            if expected and observed and expected.isdisjoint(observed):
                risks.append(f"deadline_actor_mismatch:{owners[0]}")
    return risks


def validate_alignments(
    paragraph: Paragraph, rows: Any, claims: dict[str, dict], available: set[str]
) -> tuple[list[ClaimAlignment], list[str]]:
    if not isinstance(rows, list):
        return [], ["missing_claim_alignments"]
    required = set(paragraph.claim_ids)
    fragments = assertion_fragments(paragraph.text)
    alignments = []
    risks = []
    fragments_by_claim: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        if not isinstance(row, dict):
            return [], ["invalid_claim_alignment"]
        cid, index, evidence = row.get("claim_id"), row.get("fragment"), row.get("evidence_ids")
        if (
            not isinstance(cid, str)
            or cid not in required
            or cid not in claims
            or type(index) is not int
            or index < 0
            or index >= len(fragments)
            or not isinstance(evidence, list)
            or not evidence
            or any(not isinstance(uid, str) or uid not in available for uid in evidence)
        ):
            return [], ["invalid_claim_alignment"]
        fragment = fragments[index]
        quote = fragment.group()
        claim = claims[cid]
        mandatory_sources = {claim["unit_ids"][0], *claim.get("update_evidence_ids", [])}
        if mandatory_sources - set(evidence):
            return [], ["ungrounded_claim_alignment"]
        fragments_by_claim[cid].append(quote)
        alignments.append(
            ClaimAlignment(
                claim_id=cid,
                start_char=fragment.start(),
                end_char=fragment.end(),
                evidence_ids=list(dict.fromkeys(evidence)),
            )
        )
    for cid, quotes in fragments_by_claim.items():
        claim = claims[cid]
        quote = " ".join(quotes)
        risks.extend(deadline_binding_risks(quote, [claim]))
        deadline = claim.get("deadline")
        if deadline and claim.get("lifecycle") not in INACTIVE_STATES:
            expected = date_values(deadline)
            if expected and expected.isdisjoint(date_values(quote)):
                risks.append("missing_or_wrong_claim_deadline:" + cid)
        owner = claim.get("owner")
        if owner and claim.get("kind") == "task" and not named(quote, owner):
            risks.append("missing_or_wrong_claim_owner:" + cid)
        if claim.get("condition") and not CONDITIONAL_CUE.search(quote):
            risks.append("missing_claim_condition:" + cid)
        version = claim.get("document_version")
        if version and not named(quote, version):
            risks.append("missing_or_wrong_document_version:" + cid)
    if fragments_by_claim.keys() != required:
        risks.append("missing_claim_alignments")
    if {fragment.start() for fragment in fragments} - {a.start_char for a in alignments}:
        risks.append("unmapped_output_sentence")
    return alignments, list(dict.fromkeys(risks))
