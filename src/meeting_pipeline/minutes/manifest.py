"""Traceability manifest generator linking fields, facts, audio evidence, and anchors.

Specification: Section 4 and 7 of docs/PLAN_BIEU_MAU_BIEN_BAN_V1.md.
"""

from __future__ import annotations

import logging
from pathlib import Path

from meeting_pipeline.minutes.schemas import (
    FactStatus,
    MeetingFact,
    MinutesManifest,
    TemplateSchema,
)

logger = logging.getLogger(__name__)


def generate_minutes_manifest(
    run_id: str,
    meeting_id: str,
    schema: TemplateSchema,
    facts: list[MeetingFact],
    template_original_sha256: str,
    normalized_docx_sha256: str,
    completed_docx_sha256: str,
    timings: dict[str, float] | None = None,
    models: dict[str, str] | None = None,
) -> MinutesManifest:
    """Build a complete provenance and traceability manifest for the completed minutes."""
    supported = sum(1 for f in facts if f.status == FactStatus.SUPPORTED)
    unknown = sum(1 for f in facts if f.status == FactStatus.UNKNOWN)
    needs_review = sum(
        1 for f in facts if f.status in (FactStatus.NEEDS_REVIEW, FactStatus.CONFLICTING)
    )

    return MinutesManifest(
        schema_version="1.0",
        run_id=run_id,
        meeting_id=meeting_id,
        template_id=schema.template_id,
        template_filename=schema.template_name,
        template_original_sha256=template_original_sha256,
        normalized_docx_sha256=normalized_docx_sha256,
        completed_docx_sha256=completed_docx_sha256,
        fields_count=len(schema.fields),
        facts_supported_count=supported,
        facts_unknown_count=unknown,
        facts_needs_review_count=needs_review,
        fields=schema.fields,
        facts=facts,
        timings=timings or {},
        models=models or {"schema_mapper": schema.proposed_by, "fact_extractor": "m2_rules"},
    )


def save_minutes_manifest(manifest: MinutesManifest, output_path: Path) -> None:
    """Save manifest to minutes/manifest.json."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        manifest.model_dump_json(indent=2),
        encoding="utf-8",
    )
    logger.info("Saved minutes manifest to %s", output_path)
