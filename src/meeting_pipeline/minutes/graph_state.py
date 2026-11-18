"""Project the current state while retaining the source events and their history."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from meeting_pipeline.minutes.graph_contracts import (
    INACTIVE_STATES,
    Event,
    FieldUpdate,
    GraphEdge,
    GraphUnit,
    Lifecycle,
    MeetingIssue,
)
from meeting_pipeline.minutes.graph_evidence import anchor_valid, date_values

TRANSITIONS: dict[str, Lifecycle] = {
    "withdraws": "withdrawn",
    "supersedes": "superseded",
    "accepts": "accepted",
}
STATE_RELATIONS = {"amends", *TRANSITIONS}
ISSUE_EVENTS = {"proposal", "decision", "task", "amendment", "withdrawal", "vote", "unresolved"}
STATE_CUES = {
    "withdraws": r"\b(?:rút|hủy|huỷ|bỏ đề xuất)\b",
    "amends": r"\b(?:đổi|thay|chuyển|sửa|bổ sung|dời|lùi|điều chỉnh|gia hạn)\b",
    "supersedes": r"\b(?:thay|đổi|chuyển|sửa|dời|lùi|điều chỉnh|không dùng)\b",
    "accepts": r"\b(?:thống nhất|thông qua|quyết định|kết luận|chốt)\b",
}
MODAL_PREFIX = re.compile(
    r"\b(?:không|chưa|đừng|đề nghị|đề xuất|kiến nghị|dự kiến|nếu|giả sử|có thể|cần|nên|sẽ)\b",
    re.I,
)


def asserted_cue(text: str, kind: str) -> bool:
    for clause in re.split(r"[.!?;]", text):
        match = re.search(STATE_CUES[kind], clause, re.I)
        if match and not MODAL_PREFIX.search(clause[: match.start()]):
            return True
    return False


def resolve_relations(
    events: list[Event], units: dict[str, GraphUnit], candidates: list[dict[str, Any]]
) -> tuple[list[GraphEdge], list[MeetingIssue], list[str]]:
    by_id = {event.event_id: event for event in events}
    order = {event.event_id: i for i, event in enumerate(events)}
    relations = {}
    warnings = []
    for row in candidates:
        edge = GraphEdge.model_validate(row)
        source, target = by_id.get(edge.source), by_id.get(edge.target)
        if not source or not target or source.event_id == target.event_id:
            warnings.append("missing_relation_endpoint")
            continue
        if any(uid not in units for uid in edge.evidence_ids):
            warnings.append("missing_relation_evidence")
            continue
        quotes = [a for a in edge.anchors if anchor_valid(a, units)]
        anchors = []
        for event in (source, target):
            unit = units[event.unit_ids[0]]
            anchor = next(
                (
                    a
                    for a in quotes
                    if event.anchor
                    and a.unit_id == unit.unit_id
                    and event.anchor.start_char
                    <= a.start_char
                    < a.end_char
                    <= event.anchor.end_char
                ),
                event.anchor,
            )
            if anchor:
                anchors.append(anchor)
        edge.anchors = anchors
        edge.evidence_ids = list(dict.fromkeys(a.unit_id for a in anchors))
        edge.asserted = (
            edge.asserted
            and len(anchors) == 2
            and source.session_id == target.session_id
            and order[target.event_id] < order[source.event_id]
        )
        key = (edge.source, edge.target, edge.kind)
        if key not in relations or len(quotes) >= 2:
            relations[key] = edge

    competing = Counter(
        edge.source for edge in relations.values() if edge.kind in STATE_RELATIONS and edge.asserted
    )
    parent = {event.event_id: event.event_id for event in events}

    def issue_root(event_id: str) -> str:
        root = event_id
        while parent[root] != root:
            root = parent[root]
        while parent[event_id] != root:
            following = parent[event_id]
            parent[event_id] = root
            event_id = following
        return root

    edges = []
    for edge in sorted(relations.values(), key=lambda value: order[value.source]):
        source, target = by_id[edge.source], by_id[edge.target]
        if edge.kind in STATE_RELATIONS:
            source_text = source.anchor.quote if source.anchor else source.text
            old_dates = date_values(target.text)
            current_dates = date_values(source_text)
            previous_deadline = target.current_value("deadline")
            if previous_deadline:
                old_dates = date_values(previous_deadline) or old_dates
            same_issue = bool(
                source.issue.strip()
                and source.issue.strip().casefold() == target.issue.strip().casefold()
                and re.search(rf"(?<!\w){re.escape(source.issue.strip())}(?!\w)", source_text, re.I)
            )
            nearby_reference = bool(
                order[source.event_id] == order[target.event_id] + 1
                and re.search(
                    r"\b(?:đề xuất|phương án|nhiệm vụ|việc|hạn)\s+(?:này|đó|vừa nêu)\b",
                    source_text,
                    re.I,
                )
            )
            version_mismatch = (
                edge.kind == "accepts"
                and source.document_version
                and target.current_value("document_version")
                and source.document_version.casefold()
                != target.current_value("document_version").casefold()
            )
            supported = (
                edge.asserted
                and competing[source.event_id] == 1
                and (old_dates.intersection(current_dates) or same_issue or nearby_reference)
                and asserted_cue(source_text, edge.kind)
                and source.kind not in {"proposal", "question", "unresolved"}
                and target.kind in ISSUE_EVENTS
                and target.lifecycle not in INACTIVE_STATES
                and not version_mismatch
            )
            if edge.kind == "accepts":
                supported = (
                    supported
                    and source.kind == "decision"
                    and target.kind in {"proposal", "task", "amendment", "decision"}
                )
            if edge.kind == "supersedes" and source.kind == "amendment" and source.deadline:
                edge.kind, edge.field = "amends", "deadline"
            if edge.kind == "amends" and not edge.field and source.deadline:
                edge.field = "deadline"
            if edge.kind == "amends":
                field = edge.field
                value = getattr(source, field) if field else None
                evidence = source.field_evidence.get(field) if field else None
                supported = (
                    supported and value and evidence and source.kind in {"amendment", "decision"}
                )
                if supported and field and evidence and value:
                    target.amendments[field] = FieldUpdate(
                        value=value, source_event_id=source.event_id, evidence=evidence
                    )
            elif edge.kind in {"withdraws", "supersedes"} and len(old_dates) > 1:
                supported = supported and old_dates.issubset(current_dates)
            if supported:
                if edge.kind in TRANSITIONS:
                    target.lifecycle = TRANSITIONS[edge.kind]
                target.state_evidence.extend(
                    a for a in edge.anchors if a not in target.state_evidence
                )
                parent[issue_root(source.event_id)] = issue_root(target.event_id)
            else:
                warnings.append("unconfirmed_state_transition:" + source.event_id)
                edge.kind, edge.asserted, edge.field = "refers_to", False, None
        edges.append(edge)

    grouped: dict[str, list[Event]] = {}
    for event in events:
        if event.kind in ISSUE_EVENTS or parent[event.event_id] != event.event_id:
            grouped.setdefault(issue_root(event.event_id), []).append(event)
    issues = []
    for root, members in grouped.items():
        issue_id = "issue:" + root
        for event in members:
            event.issue_id = issue_id
        issues.append(
            MeetingIssue(
                issue_id=issue_id,
                title=by_id[root].issue or by_id[root].text[:100],
                event_ids=[event.event_id for event in members],
                effective_event_ids=[
                    event.event_id
                    for event in members
                    if event.lifecycle not in INACTIVE_STATES
                    and (
                        event.kind in {"task", "decision", "vote"} or event.lifecycle == "accepted"
                    )
                ],
            )
        )
    return edges, issues, list(dict.fromkeys(warnings))
