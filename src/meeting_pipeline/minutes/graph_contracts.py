"""Versioned meeting semantics, separate from the Word template's DocGraph."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

EventKind = Literal[
    "information",
    "proposal",
    "question",
    "response",
    "objection",
    "agreement",
    "decision",
    "task",
    "withdrawal",
    "amendment",
    "vote",
    "unresolved",
    "filler",
]
RelationKind = Literal[
    "contains",
    "next",
    "about",
    "spoken_by",
    "evidenced_by",
    "assigned_to",
    "refers_to",
    "supports",
    "opposes",
    "amends",
    "withdraws",
    "supersedes",
    "accepts",
    "depends_on",
    "applies_to_version",
    "same_topic_candidate",
    "on_issue",
]
Variant = Literal["B", "C", "D", "E", "F"]
FactField = Literal["owner", "deadline", "condition", "document_version"]
FACT_FIELDS: tuple[FactField, ...] = ("owner", "deadline", "condition", "document_version")
Lifecycle = Literal["stated", "proposed", "accepted", "withdrawn", "superseded", "unresolved"]
INACTIVE_STATES = {"withdrawn", "superseded"}


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()


IDENTIFIER_FIELDS = {
    "unit_id",
    "item_id",
    "event_id",
    "unit_ids",
    "evidence_unit_ids",
    "evidence_ids",
    "claim_id",
    "claim_ids",
    "target_unit_id",
    "source",
    "target",
    "missing_claim_ids",
    "source_event_id",
    "update_evidence_ids",
    "state_evidence_ids",
}


def remap_identifiers(value: Any, mapping: dict[str, str], field: str = "") -> Any:
    """Keep stable public IDs in storage, but use short per-request aliases with an LLM."""
    if isinstance(value, dict):
        return {key: remap_identifiers(item, mapping, key) for key, item in value.items()}
    if isinstance(value, list):
        return [remap_identifiers(item, mapping, field) for item in value]
    if isinstance(value, str) and field in IDENTIFIER_FIELDS:
        return mapping.get(value, value)
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceSpan(StrictModel):
    turn_id: str
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=0)
    text: str
    source_id: str = "primary"
    start_sec: float = 0
    end_sec: float = 0


class GraphUnit(StrictModel):
    unit_id: str
    turn_id: str
    turn_ids: list[str] = Field(default_factory=list)
    speaker: str = ""
    speaker_id: str | None = None
    session_id: str = "session_0"
    episode_id: str = "episode_0"
    start_sec: float = 0
    end_sec: float = 0
    original: str
    text: str
    needs_review: bool = False
    user_edited: bool = False
    sources: list[SourceSpan] = Field(default_factory=list)


class EvidenceAnchor(StrictModel):
    """Character offsets into GraphUnit.original, whose SourceSpans locate the turn."""

    unit_id: str
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    quote: str = Field(min_length=1)
    method: Literal["literal", "speaker_self_reference"] = "literal"


class FieldUpdate(StrictModel):
    value: str
    source_event_id: str
    evidence: EvidenceAnchor


class Event(StrictModel):
    event_id: str
    unit_ids: list[str]
    kind: EventKind = "information"
    text: str
    issue: str = ""
    owner: str | None = None
    deadline: str | None = None
    condition: str | None = None
    document_version: str | None = None
    session_id: str = "session_0"
    lifecycle: Lifecycle = "stated"
    verification: Literal["supported", "needs_review", "conflicting", "unknown"] = "needs_review"
    extraction: Literal["model", "source_fallback"] = "model"
    warnings: list[str] = Field(default_factory=list)
    editorial_role: str = "discussion"
    anchor: EvidenceAnchor | None = None
    field_evidence: dict[FactField, EvidenceAnchor] = Field(default_factory=dict)
    state_evidence: list[EvidenceAnchor] = Field(default_factory=list)
    amendments: dict[FactField, FieldUpdate] = Field(default_factory=dict)
    issue_id: str | None = None

    def current_value(self, field: FactField) -> str | None:
        update = self.amendments.get(field)
        return update.value if update else getattr(self, field)

    def current_evidence(self, field: FactField) -> EvidenceAnchor | None:
        update = self.amendments.get(field)
        return update.evidence if update else self.field_evidence.get(field)


class GraphNode(StrictModel):
    node_id: str
    kind: str
    label: str
    attributes: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(StrictModel):
    source: str
    target: str
    kind: RelationKind
    evidence_ids: list[str] = Field(default_factory=list)
    weight: float | None = None
    asserted: bool = True
    anchors: list[EvidenceAnchor] = Field(default_factory=list)
    field: FactField | None = None


class MeetingIssue(StrictModel):
    issue_id: str
    title: str
    event_ids: list[str]
    effective_event_ids: list[str]


class MeetingGraph(StrictModel):
    schema_version: str = "1.0"
    meeting_id: str
    input_sha256: str
    graph_id: str
    units: list[GraphUnit]
    events: list[Event]
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    topics: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    issues: list[MeetingIssue] = Field(default_factory=list)


class ClaimAlignment(StrictModel):
    claim_id: str
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    evidence_ids: list[str] = Field(min_length=1)


class Paragraph(StrictModel):
    text: str
    claim_ids: list[str]
    evidence_ids: list[str] = Field(default_factory=list)
    verification: Literal["checked", "source_fallback", "needs_review"] = "needs_review"
    alignments: list[ClaimAlignment] = Field(default_factory=list)


class OutlineItem(StrictModel):
    item_id: str
    role: str
    text: str
    claim_ids: list[str]
    evidence_ids: list[str]
    lifecycle: str = "stated"
    owner: str | None = None
    deadline: str | None = None
    condition: str | None = None
    verification: str = "needs_review"
    issue_id: str | None = None
    field_evidence: dict[FactField, EvidenceAnchor] = Field(default_factory=dict)
    priority: Literal["required", "optional"] = "required"
    included: bool = True


class Section(StrictModel):
    section_id: str
    title: str
    claim_ids: list[str]
    claim_groups: dict[str, list[str]] = Field(default_factory=dict)
    paragraphs: list[Paragraph] = Field(default_factory=list)
    topic_id: str | None = None
    topic_ids: list[str] = Field(default_factory=list)
    summary: str = ""
    outline: list[OutlineItem] = Field(default_factory=list)
    title_edited: bool = False


class StyleRule(StrictModel):
    rule_id: str
    instruction: str
    scope: str = "general"
    source_edit_ids: list[str] = Field(default_factory=list)
    support_count: int = Field(default=1, ge=1)
    active: bool = False


class StyleProfile(StrictModel):
    profile_id: str = "minimal_v1"
    revision: int = 1
    rules: list[StyleRule] = Field(default_factory=list)
    provenance: str = "system_defaults"


def default_style() -> StyleProfile:
    instructions = [
        "Viết thành đoạn theo vấn đề; gộp phát biểu liên quan và giảm lặp tên người.",
        "Dùng giọng trung tính, câu rõ ràng; không thêm lời đánh giá hoặc câu hành chính sáo rỗng.",
        "Giữ tên ở phân công và ý kiến cần phân biệt. Trình bày rõ người, việc và thời hạn.",
        "Chỉ dùng đề mục ngắn khi cần; không đánh số cứng mọi đoạn văn.",
    ]
    return StyleProfile(
        rules=[
            StyleRule(
                rule_id=f"default_{i}",
                instruction=text,
                active=True,
                scope=("discussion", "general", "task", "general")[i],
            )
            for i, text in enumerate(instructions)
        ]
    )
