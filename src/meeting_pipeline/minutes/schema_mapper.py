"""Schema mapping and proposal service (M0 rule-based baseline and M1 local LLM adapter).

Maps candidate anchors in a DocGraph to semantic minutes fields with strict
validation against hallucinated anchors, field collisions, and dropped placeholders.
Specification: Section 5 (F2) of docs/PLAN_BIEU_MAU_BIEN_BAN_V1.md.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from meeting_pipeline.minutes.schemas import (
    CandidateAnchor,
    DocGraph,
    PlaceholderType,
    SemanticFieldType,
    TemplateField,
    TemplateSchema,
)

logger = logging.getLogger(__name__)


class SchemaValidationError(Exception):
    """Raised when a proposed schema fails structural validation."""


class SchemaValidator:
    """Validates that a proposed schema adheres to all document invariants."""

    @staticmethod
    def validate(
        doc_graph: DocGraph,
        proposed_fields: list[TemplateField],
        unmapped_anchors: list[str] | None = None,
    ) -> tuple[list[TemplateField], list[str], list[str]]:
        """Validate candidate anchors, uniqueness, and completeness.

        Returns (validated_fields, unmapped_anchor_ids, issues).
        """
        issues: list[str] = []
        valid_anchors_map: dict[str, CandidateAnchor] = {
            a.anchor_id: a for a in doc_graph.all_anchors
        }

        validated_fields: list[TemplateField] = []
        used_anchors: set[str] = set()

        for field in proposed_fields:
            # Invariant 1: Anchor ID must exist in real document
            if field.anchor_id not in valid_anchors_map:
                issues.append(
                    f"Trường '{field.field_id}' tham chiếu đến "
                    f"anchor không tồn tại: '{field.anchor_id}'"
                )
                continue

            # Invariant 2: No duplicate anchor mapping
            if field.anchor_id in used_anchors:
                issues.append(
                    f"Anchor '{field.anchor_id}' bị trùng lặp, gán cho nhiều hơn 1 trường."
                )
                field.mapper_status = "needs_review"
                field.review_reason = "Anchor bị gán trùng lặp"

            used_anchors.add(field.anchor_id)
            validated_fields.append(field)

        # Invariant 3: Unmapped anchors must be explicitly cataloged
        unmapped_set = set(unmapped_anchors or [])
        all_anchor_ids = set(valid_anchors_map.keys())
        missing_unmapped = all_anchor_ids - used_anchors - unmapped_set
        unmapped_list = sorted(list(unmapped_set | missing_unmapped))

        if missing_unmapped:
            logger.info("Found %d candidate anchors left unmapped", len(missing_unmapped))

        return validated_fields, unmapped_list, issues


class M0RuleSchemaMapper:
    """Rule-based heuristic schema mapper for Vietnamese administrative meeting templates."""

    def propose_schema(self, doc_graph: DocGraph) -> TemplateSchema:
        """Map candidate anchors to semantic fields using domain rules."""
        fields: list[TemplateField] = []
        unmapped: list[str] = []

        # Track field ID occurrences to prevent duplicates
        id_counts: dict[str, int] = {}

        def _make_field_id(base_name: str) -> str:
            count = id_counts.get(base_name, 0)
            id_counts[base_name] = count + 1
            return base_name if count == 0 else f"{base_name}_{count}"

        for anchor in doc_graph.all_anchors:
            lbl = anchor.nearby_label.lower()
            sec = anchor.section_path.lower()
            raw_lbl = anchor.nearby_label or anchor.section_path or "Chỗ trống"

            semantic_type = SemanticFieldType.CUSTOM
            field_id = "custom_field"
            condition = "none"
            needs_review = False
            review_reason: str | None = None

            # 1. Party specific rules (must be checked before generic date/meeting_month_year)
            if "đảng phí" in lbl:
                semantic_type = SemanticFieldType.PARTY_DUES
                field_id = _make_field_id("party_dues")
            elif "tình hình đảng viên" in lbl:
                semantic_type = SemanticFieldType.PARTY_MEMBER_STATUS
                field_id = _make_field_id("party_member_status")
            elif "đạo đức hcm" in lbl:
                semantic_type = SemanticFieldType.MORAL_STUDY
                field_id = _make_field_id("moral_study")
            elif "lãnh đạo của chi bộ" in lbl:
                semantic_type = SemanticFieldType.LEADERSHIP_FEEDBACK
                field_id = _make_field_id("leadership_feedback")

            # 2. Organization & Document Number
            elif "cơ quan" in lbl or "đơn vị" in lbl or "đảng ủy" in lbl or "chi bộ" in lbl:
                semantic_type = SemanticFieldType.ORGANIZATION
                field_id = _make_field_id("organization")
            elif "số:" in lbl or "ký hiệu" in lbl:
                semantic_type = SemanticFieldType.DOCUMENT_NUMBER
                field_id = _make_field_id("doc_number")

            # 3. Date and Time (Header or Opening)
            elif (
                "tháng" in lbl
                and "20" in lbl
                and ("header" in sec or "mở đầu" in sec or "tháng" == lbl)
            ):
                semantic_type = SemanticFieldType.MEETING_MONTH_YEAR
                field_id = _make_field_id("meeting_month_year")
            elif "kết thúc" in lbl or "kết thúc lúc" in lbl:
                semantic_type = SemanticFieldType.MEETING_END_TIME
                field_id = _make_field_id("end_time")
            elif (
                "thời gian" in lbl or "hôm nay, vào lúc" in lbl or ("giờ" in lbl and "ngày" in lbl)
            ):
                semantic_type = SemanticFieldType.MEETING_START_TIME
                field_id = _make_field_id("start_time")
            elif "ngày" in lbl or "tháng" in lbl or "năm" in lbl:
                semantic_type = SemanticFieldType.DOCUMENT_DATE_PLACE
                field_id = _make_field_id("doc_date")

            # 3. Location
            elif "địa điểm" in lbl or "tại" in lbl:
                semantic_type = SemanticFieldType.MEETING_LOCATION
                field_id = _make_field_id("location")

            # 4. Topic / Agenda
            elif "về việc" in lbl or "v/v" in lbl:
                semantic_type = SemanticFieldType.MEETING_TOPIC
                field_id = _make_field_id("topic")
            elif "diễn ra cuộc họp với nội dung" in lbl or "chương trình của cuộc họp" in lbl:
                semantic_type = SemanticFieldType.MEETING_AGENDA_SUMMARY
                field_id = _make_field_id("agenda_summary")

            # 5. Leadership / Roles
            elif "chủ trì" in lbl or "chủ tọa" in lbl or "bí thư" in lbl:
                semantic_type = SemanticFieldType.PERSON_NAME
                field_id = _make_field_id("chairperson_name")
            elif "thư ký" in lbl or "người ghi biên bản" in lbl:
                semantic_type = SemanticFieldType.PERSON_NAME
                field_id = _make_field_id("secretary_name")
            elif "chức vụ" in lbl:
                semantic_type = SemanticFieldType.PERSON_ROLE
                field_id = _make_field_id("person_role")
            elif "thành phần" in lbl or "người tham dự" in lbl:
                semantic_type = SemanticFieldType.ATTENDEE_LIST
                field_id = _make_field_id("attendees")

            # 6. Content / Discussion
            elif "nội dung cuộc họp" in sec or "nội dung" in lbl or "thảo luận" in lbl:
                semantic_type = SemanticFieldType.DISCUSSION_SUMMARY
                field_id = _make_field_id("discussion_summary")

            # 7. Voting (check 'không tán thành' before 'tán thành' due to substring match)
            elif "tổng số phiếu" in lbl:
                semantic_type = SemanticFieldType.VOTING_TOTAL
                field_id = _make_field_id("voting_total")
                condition = "conditional"
            elif "không tán thành" in lbl and "%" in lbl:
                semantic_type = SemanticFieldType.VOTING_REJECTED_PERCENT
                field_id = _make_field_id("voting_rejected_pct")
                condition = "conditional"
            elif "không tán thành" in lbl:
                semantic_type = SemanticFieldType.VOTING_REJECTED_COUNT
                field_id = _make_field_id("voting_rejected_count")
                condition = "conditional"
            elif "tán thành" in lbl and "%" in lbl:
                semantic_type = SemanticFieldType.VOTING_APPROVED_PERCENT
                field_id = _make_field_id("voting_approved_pct")
                condition = "conditional"
            elif "tán thành" in lbl:
                semantic_type = SemanticFieldType.VOTING_APPROVED_COUNT
                field_id = _make_field_id("voting_approved_count")
                condition = "conditional"

            # 8. Conclusions / Decisions / Actions
            elif "kết luận" in sec or "kết luận" in lbl:
                semantic_type = SemanticFieldType.DECISION_LIST
                field_id = _make_field_id("decisions")
            elif "nhiệm vụ" in lbl or "phân công" in lbl:
                semantic_type = SemanticFieldType.ACTION_ITEM
                field_id = _make_field_id("action_items")

            # 10. Signatures
            elif (
                anchor.placeholder_type == PlaceholderType.SIGNATURE_BLOCK
                or "chữ ký" in sec
                or "chữ ký" in lbl
            ):
                semantic_type = SemanticFieldType.SIGNATURE
                field_id = _make_field_id("signature")

            else:
                # Ambiguous anchor
                semantic_type = SemanticFieldType.CUSTOM
                field_id = _make_field_id("custom_field")
                needs_review = True
                review_reason = f"Không xác định rõ ý nghĩa ngữ cảnh: '{raw_lbl}'"

            fields.append(
                TemplateField(
                    field_id=field_id,
                    anchor_id=anchor.anchor_id,
                    raw_label=raw_lbl,
                    semantic_type=semantic_type,
                    section=anchor.section_path or "General",
                    condition=condition,  # type: ignore[arg-type]
                    cardinality="many" if anchor.is_multiline else "one",
                    mapper_status="needs_review" if needs_review else "proposed",
                    review_reason=review_reason,
                )
            )

        validated, unmapped_list, issues = SchemaValidator.validate(doc_graph, fields, unmapped)
        if issues:
            logger.warning("M0 schema validator noticed: %s", issues)

        return TemplateSchema(
            schema_version="1.0",
            template_id=doc_graph.template_id,
            template_name=doc_graph.template_name,
            template_hash=doc_graph.normalized_docx_sha256,
            fields=validated,
            unmapped_anchors=unmapped_list,
            proposed_by="m0_rules",
        )


class M1Qwen3SchemaMapper:
    """Local LLM adapter proposing field semantics via constrained JSON grammar.

    Specification: Section 5 (F2) of docs/PLAN_BIEU_MAU_BIEN_BAN_V1.md.
    """

    def __init__(self, model_name: str = "Qwen/Qwen3-4B-Instruct-2507") -> None:
        self.model_name = model_name

    def is_available(self) -> bool:
        """Check whether local runtime weights are available."""
        # Check if local weights exist in cache or ollama
        return False  # Weights not downloaded locally

    def propose_schema(self, doc_graph: DocGraph) -> tuple[TemplateSchema | None, str, float]:
        """Propose schema via local LLM if available; otherwise report not_run.

        Returns (schema_or_none, status, duration_sec).
        """
        t0 = time.perf_counter()
        if not self.is_available():
            dur = time.perf_counter() - t0
            logger.info("M1 Qwen3 model weights not available locally. Status: not_run")
            return None, "not_run", dur

        # If model runtime were present, build compact JSON prompt:
        # prompt = self._build_prompt(doc_graph)
        # result = self._call_local_runtime(prompt)
        return None, "not_run", time.perf_counter() - t0

    def _build_prompt(self, doc_graph: DocGraph) -> str:
        """Build compact DocGraph prompt containing only structural labels and IDs."""
        compact_items: list[dict[str, Any]] = [
            {
                "anchor_id": a.anchor_id,
                "label": a.nearby_label,
                "section": a.section_path,
                "type": a.placeholder_type.value,
            }
            for a in doc_graph.all_anchors
        ]
        return json.dumps(compact_items, ensure_ascii=False)


def save_schema(schema: TemplateSchema, output_path: Path) -> None:
    """Save template schema to a JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        schema.model_dump_json(indent=2),
        encoding="utf-8",
    )


def load_schema(input_path: Path) -> TemplateSchema:
    """Load template schema from a JSON file."""
    data = json.loads(input_path.read_text(encoding="utf-8"))
    return TemplateSchema.model_validate(data)
