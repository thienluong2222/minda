"""Data contracts and schemas for form understanding and meeting minutes generation.

Implements Section 4 of docs/PLAN_BIEU_MAU_BIEN_BAN_V1.md.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


def get_iso_timestamp() -> str:
    """Return current UTC timestamp in ISO format."""
    return datetime.now(UTC).isoformat()


class BlockType(StrEnum):
    """Structural type of document block in DocGraph."""

    PARAGRAPH = "paragraph"
    HEADING = "heading"
    TABLE_CELL = "table_cell"
    HEADER = "header"
    FOOTER = "footer"


class PlaceholderType(StrEnum):
    """Type of placeholder pattern detected by parser."""

    DOTTED_LINE = "dotted_line"
    UNDERLINE = "underline"
    EMPTY_CELL = "empty_cell"
    TEXT_PLACEHOLDER = "text_placeholder"
    SIGNATURE_BLOCK = "signature_block"
    REPEATED_ROW = "repeated_row"


class SemanticFieldType(StrEnum):
    """Semantic domain categories for minutes fields."""

    ORGANIZATION = "organization"
    DOCUMENT_NUMBER = "document_number"
    DOCUMENT_DATE_PLACE = "document_date_place"
    MEETING_TOPIC = "meeting_topic"
    MEETING_MONTH_YEAR = "meeting_month_year"
    MEETING_START_TIME = "meeting_start_time"
    MEETING_END_TIME = "meeting_end_time"
    MEETING_LOCATION = "meeting_location"
    MEETING_AGENDA_SUMMARY = "meeting_agenda_summary"
    MEETING_AGENDA = "meeting_agenda"
    PERSON_NAME = "person_name"
    PERSON_ROLE = "person_role"
    ATTENDEE_LIST = "attendee_list"
    DISCUSSION_SUMMARY = "discussion_summary"
    DECISION_LIST = "decision_list"
    ACTION_ITEM = "action_item"
    VOTING_TOTAL = "voting_total"
    VOTING_APPROVED_COUNT = "voting_approved_count"
    VOTING_APPROVED_PERCENT = "voting_approved_percent"
    VOTING_REJECTED_COUNT = "voting_rejected_count"
    VOTING_REJECTED_PERCENT = "voting_rejected_percent"
    SIGNATURE = "signature"
    PARTY_DUES = "party_dues"
    PARTY_MEMBER_STATUS = "party_member_status"
    NEWS_INFO = "news_info"
    RESOLUTION_EVALUATION = "resolution_evaluation"
    MORAL_STUDY = "moral_study"
    LEADERSHIP_FEEDBACK = "leadership_feedback"
    CUSTOM = "custom"


class CandidateAnchor(BaseModel):
    """Position of a fillable hole identified in the document structure."""

    anchor_id: str = Field(description="Unique stable ID, e.g. anc_p13_0")
    block_id: str = Field(description="Block ID within DocGraph, e.g. blk_p13")
    element_path: str = Field(description="Detailed path in docx, e.g. p[13]/r[2]")
    start_offset: int = Field(default=0, description="Char offset in block text")
    end_offset: int = Field(default=0, description="Char offset in block text")
    placeholder_text: str = Field(description="Original placeholder text, e.g. ................")
    placeholder_type: PlaceholderType = Field(default=PlaceholderType.DOTTED_LINE)
    nearby_label: str = Field(default="", description="Surrounding contextual label")
    section_path: str = Field(default="", description="Hierarchical section name")
    is_multiline: bool = Field(default=False)
    repeat_group_id: str | None = Field(default=None)


class DocBlock(BaseModel):
    """A structural block in the Word document representation."""

    block_id: str
    order: int
    block_type: BlockType
    raw_text: str
    section_path: str = ""
    element_path: str
    style_name: str = ""
    candidate_anchors: list[CandidateAnchor] = Field(default_factory=list)


class DocGraph(BaseModel):
    """Graph of structural blocks and fillable candidate anchors in a template."""

    schema_version: str = "1.0"
    template_id: str
    template_name: str
    original_sha256: str
    normalized_docx_sha256: str
    created_at: str = Field(default_factory=get_iso_timestamp)
    blocks: list[DocBlock] = Field(default_factory=list)
    unmapped_warnings: list[str] = Field(default_factory=list)

    @property
    def all_anchors(self) -> list[CandidateAnchor]:
        anchors: list[CandidateAnchor] = []
        for blk in self.blocks:
            anchors.extend(blk.candidate_anchors)
        return anchors


class TemplateField(BaseModel):
    """A semantic field definition bound to an anchor."""

    field_id: str
    anchor_id: str
    raw_label: str
    semantic_type: SemanticFieldType = SemanticFieldType.CUSTOM
    section: str = ""
    condition: Literal["none", "optional", "conditional"] = "none"
    cardinality: Literal["one", "many"] = "one"
    repeat_group_id: str | None = None
    allowed_source_types: list[str] = Field(
        default_factory=lambda: ["transcript", "meeting_metadata", "user_review"]
    )
    mapper_status: Literal["proposed", "approved", "rejected", "needs_review"] = "proposed"
    review_reason: str | None = None


class TemplateSchema(BaseModel):
    """The schema specification of fillable fields for a template."""

    schema_version: str = "1.0"
    template_id: str
    template_name: str
    template_hash: str
    fields: list[TemplateField] = Field(default_factory=list)
    unmapped_anchors: list[str] = Field(default_factory=list)
    revision: int = 1
    created_at: str = Field(default_factory=get_iso_timestamp)
    updated_at: str = Field(default_factory=get_iso_timestamp)
    proposed_by: Literal["m0_rules", "m1_qwen3", "user_manual"] = "m0_rules"


class EvidenceRef(BaseModel):
    """Traceability link connecting an extracted fact to its audio/transcript source."""

    run_id: str
    turn_id: str
    source_id: str = "primary"
    start_sec: float = 0.0
    end_sec: float = 0.0
    clip_path: str | None = None
    source_kind: Literal["transcript", "meeting_metadata", "user_edit", "computed"] = "transcript"
    text_snippet: str = ""
    confidence: float | None = None


class FactStatus(StrEnum):
    """Grounding status of an extracted fact."""

    SUPPORTED = "supported"
    UNKNOWN = "unknown"
    CONFLICTING = "conflicting"
    NEEDS_REVIEW = "needs_review"


class MeetingFact(BaseModel):
    """An extracted, validated factual value for a template field."""

    field_id: str
    value: Any = None  # str, list[str], or None
    status: FactStatus = FactStatus.UNKNOWN
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    confidence: float | None = None
    reason: str | None = None
    transcript_revision: int = 1
    user_edited: bool = False
    updated_at: str = Field(default_factory=get_iso_timestamp)


class MinutesManifest(BaseModel):
    """Complete provenance manifest for completed minutes document."""

    schema_version: str = "1.0"
    run_id: str
    meeting_id: str
    template_id: str
    template_filename: str
    template_original_sha256: str
    normalized_docx_sha256: str
    completed_docx_sha256: str
    created_at: str = Field(default_factory=get_iso_timestamp)
    fields_count: int
    facts_supported_count: int
    facts_unknown_count: int
    facts_needs_review_count: int
    fields: list[TemplateField] = Field(default_factory=list)
    facts: list[MeetingFact] = Field(default_factory=list)
    timings: dict[str, float] = Field(default_factory=dict)
    models: dict[str, str] = Field(default_factory=dict)


class RunMetrics(BaseModel):
    """Timing and resource metrics measured with perf_counter."""

    convert_sec: float = 0.0
    parse_sec: float = 0.0
    schema_proposal_sec: float = 0.0
    retrieval_sec: float = 0.0
    extraction_sec: float = 0.0
    render_sec: float = 0.0
    total_wall_sec: float = 0.0
    field_count: int = 0
    turn_count: int = 0
    model_calls: int = 0
