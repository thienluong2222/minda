"""Minutes service orchestrating normalization, schema mapping,
fact extraction, rendering, and export.

Specification: Section 3, 5 (F0-F5), and 7 of docs/PLAN_BIEU_MAU_BIEN_BAN_V1.md.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
import zipfile
from pathlib import Path
from typing import Any

from meeting_pipeline.minutes.converter import normalize_template
from meeting_pipeline.minutes.doc_parser import parse_template_document
from meeting_pipeline.minutes.evidence_retrieval import load_indexed_turns
from meeting_pipeline.minutes.fact_extractor import M2RuleFactExtractor
from meeting_pipeline.minutes.manifest import generate_minutes_manifest, save_minutes_manifest
from meeting_pipeline.minutes.renderer import render_completed_document
from meeting_pipeline.minutes.schema_mapper import (
    M0RuleSchemaMapper,
    M1Qwen3SchemaMapper,
    SchemaValidator,
    load_schema,
    save_schema,
)
from meeting_pipeline.minutes.schemas import (
    DocGraph,
    MeetingFact,
    RunMetrics,
    TemplateField,
)
from meeting_pipeline.minutes.visual_qa import render_document_to_image

logger = logging.getLogger(__name__)


def _write_json(path: Path, data: Any) -> None:
    """Safely write JSON file with parent directory creation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


class MinutesService:
    """Orchestrates end-to-end meeting minutes generation from audio runs and Word templates."""

    def process_template_for_run(
        self,
        template_file_path: Path,
        run_dir: Path,
        meeting_metadata: dict[str, Any] | None = None,
        use_model: bool = False,
    ) -> dict[str, Any]:
        """Execute full minutes pipeline from uploaded template to completed.docx and manifest."""
        t_start = time.perf_counter()
        metrics = RunMetrics()

        template_dir = run_dir / "template"
        minutes_dir = run_dir / "minutes"
        exports_dir = run_dir / "exports"
        template_dir.mkdir(parents=True, exist_ok=True)
        minutes_dir.mkdir(parents=True, exist_ok=True)
        exports_dir.mkdir(parents=True, exist_ok=True)

        # Preserve uploaded template
        ext = template_file_path.suffix.lower()
        orig_copy = template_dir / f"original{ext}"
        shutil.copy2(template_file_path, orig_copy)

        # 1. Normalization (convert .doc if needed)
        t0 = time.perf_counter()
        converted = normalize_template(orig_copy, template_dir, "normalized")
        metrics.convert_sec = round(time.perf_counter() - t0, 4)

        # 2. Parse DocGraph and CandidateAnchors
        t0 = time.perf_counter()
        doc_graph = parse_template_document(
            converted.normalized_docx_path,
            original_sha256=converted.original_sha256,
            template_id=template_file_path.stem,
        )
        _write_json(template_dir / "doc_graph.json", doc_graph.model_dump())
        metrics.parse_sec = round(time.perf_counter() - t0, 4)

        # 3. Schema proposal (M0 baseline + M1 model check)
        t0 = time.perf_counter()
        m0_mapper = M0RuleSchemaMapper()
        proposed_schema = m0_mapper.propose_schema(doc_graph)

        m1_status = "not_run"
        if use_model:
            m1_mapper = M1Qwen3SchemaMapper()
            m1_schema, m1_status, _ = m1_mapper.propose_schema(doc_graph)
            if m1_schema is not None:
                proposed_schema = m1_schema

        save_schema(proposed_schema, template_dir / "schema_proposal.json")
        save_schema(proposed_schema, template_dir / "schema.json")
        metrics.schema_proposal_sec = round(time.perf_counter() - t0, 4)
        metrics.field_count = len(proposed_schema.fields)

        # 4. Load audio timeline turns & retrieve evidence
        t0 = time.perf_counter()
        turns = load_indexed_turns(run_dir)
        metrics.turn_count = len(turns)
        metrics.retrieval_sec = round(time.perf_counter() - t0, 4)

        # 5. Extract facts (M2 rule-based baseline)
        t0 = time.perf_counter()
        extractor = M2RuleFactExtractor()
        facts = extractor.extract_facts(
            schema=proposed_schema,
            turns=turns,
            meeting_metadata=meeting_metadata,
            run_id=run_dir.name,
        )
        _write_json(minutes_dir / "facts.json", [f.model_dump() for f in facts])
        metrics.extraction_sec = round(time.perf_counter() - t0, 4)

        # 6. Render completed Word document
        t0 = time.perf_counter()
        completed_docx_path = exports_dir / "completed.docx"
        _, completed_sha = render_completed_document(
            normalized_docx_path=converted.normalized_docx_path,
            output_docx_path=completed_docx_path,
            doc_graph=doc_graph,
            schema=proposed_schema,
            facts=facts,
        )
        metrics.render_sec = round(time.perf_counter() - t0, 4)

        # 7. Render before/after visual QA previews
        try:
            render_document_to_image(orig_copy, template_dir, "preview_before.png")
            render_document_to_image(completed_docx_path, exports_dir, "preview_after.png")
        except Exception as exc:
            logger.warning("Visual QA image render failed: %s", exc)

        # 8. Build traceability manifest
        metrics.total_wall_sec = round(time.perf_counter() - t_start, 4)
        timings_dict = metrics.model_dump()
        _write_json(minutes_dir / "timings.json", timings_dict)

        manifest = generate_minutes_manifest(
            run_id=run_dir.name,
            meeting_id=run_dir.parent.parent.name,
            schema=proposed_schema,
            facts=facts,
            template_original_sha256=converted.original_sha256,
            normalized_docx_sha256=converted.normalized_docx_sha256,
            completed_docx_sha256=completed_sha,
            timings=timings_dict,
            models={"m0_schema": "rules", "m1_status": m1_status, "m2_facts": "rules"},
        )
        save_minutes_manifest(manifest, minutes_dir / "manifest.json")

        # 9. Package completed minutes ZIP export
        zip_path = exports_dir / "completed_minutes.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(completed_docx_path, "completed.docx")
            zf.write(minutes_dir / "manifest.json", "manifest.json")
            zf.write(minutes_dir / "facts.json", "facts.json")
            zf.write(template_dir / "schema.json", "schema.json")
            zf.write(minutes_dir / "timings.json", "timings.json")

        return {
            "status": "success",
            "run_id": run_dir.name,
            "template_id": proposed_schema.template_id,
            "fields_count": len(proposed_schema.fields),
            "facts_supported": manifest.facts_supported_count,
            "facts_unknown": manifest.facts_unknown_count,
            "facts_needs_review": manifest.facts_needs_review_count,
            "completed_docx": str(completed_docx_path),
            "manifest_json": str(minutes_dir / "manifest.json"),
            "zip_export": str(zip_path),
            "metrics": timings_dict,
        }

    def update_facts_and_re_render(
        self,
        run_dir: Path,
        updated_facts_data: list[dict[str, Any]],
    ) -> Path:
        """Update facts with user edits and re-render document without re-running ASR."""
        template_dir = run_dir / "template"
        minutes_dir = run_dir / "minutes"
        exports_dir = run_dir / "exports"

        schema_path = template_dir / "schema.json"
        doc_graph_path = template_dir / "doc_graph.json"
        normalized_docx = template_dir / "normalized.docx"

        if not schema_path.is_file() or not doc_graph_path.is_file():
            raise FileNotFoundError("Template schema or DocGraph missing in run directory.")

        schema = load_schema(schema_path)
        doc_graph_data = json.loads(doc_graph_path.read_text(encoding="utf-8"))
        doc_graph = DocGraph.model_validate(doc_graph_data)

        # Parse updated facts
        facts = [MeetingFact.model_validate(f) for f in updated_facts_data]
        for f in facts:
            f.user_edited = True
            f.transcript_revision += 1

        _write_json(minutes_dir / "facts.json", [f.model_dump() for f in facts])

        # Re-render
        completed_docx_path = exports_dir / "completed.docx"
        _, completed_sha = render_completed_document(
            normalized_docx_path=normalized_docx,
            output_docx_path=completed_docx_path,
            doc_graph=doc_graph,
            schema=schema,
            facts=facts,
        )

        try:
            render_document_to_image(completed_docx_path, exports_dir, "preview_after.png")
        except Exception as exc:
            logger.warning("Re-render visual QA failed: %s", exc)

        # Re-save manifest
        manifest_path = minutes_dir / "manifest.json"
        orig_sha = doc_graph.original_sha256
        norm_sha = doc_graph.normalized_docx_sha256
        manifest = generate_minutes_manifest(
            run_id=run_dir.name,
            meeting_id=run_dir.parent.parent.name,
            schema=schema,
            facts=facts,
            template_original_sha256=orig_sha,
            normalized_docx_sha256=norm_sha,
            completed_docx_sha256=completed_sha,
        )
        save_minutes_manifest(manifest, manifest_path)

        # Update ZIP
        zip_path = exports_dir / "completed_minutes.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(completed_docx_path, "completed.docx")
            zf.write(manifest_path, "manifest.json")
            zf.write(minutes_dir / "facts.json", "facts.json")
            zf.write(schema_path, "schema.json")

        return completed_docx_path

    def update_schema_and_re_extract(
        self,
        run_dir: Path,
        updated_fields_data: list[dict[str, Any]],
        meeting_metadata: dict[str, Any] | None = None,
    ) -> Path:
        """Approve and update schema, record audit, re-extract facts and re-render."""
        template_dir = run_dir / "template"
        minutes_dir = run_dir / "minutes"

        doc_graph_path = template_dir / "doc_graph.json"
        if not doc_graph_path.is_file():
            raise FileNotFoundError("DocGraph missing in run directory.")
        doc_graph = DocGraph.model_validate(json.loads(doc_graph_path.read_text(encoding="utf-8")))

        schema_path = template_dir / "schema.json"
        current_schema = load_schema(schema_path)

        # Validate new fields
        new_fields = [TemplateField.model_validate(f) for f in updated_fields_data]
        val_fields, unmapped, issues = SchemaValidator.validate(doc_graph, new_fields)

        # Audit review
        review_audit_path = template_dir / "schema_review.json"
        audit_history: list[dict[str, Any]] = []
        if review_audit_path.is_file():
            audit_history = json.loads(review_audit_path.read_text(encoding="utf-8"))

        audit_history.append(
            {
                "revision": current_schema.revision + 1,
                "updated_at": time.time(),
                "field_count": len(val_fields),
                "issues": issues,
            }
        )
        _write_json(review_audit_path, audit_history)

        current_schema.fields = val_fields
        current_schema.unmapped_anchors = unmapped
        current_schema.revision += 1
        current_schema.proposed_by = "user_manual"
        save_schema(current_schema, schema_path)

        # Re-extract facts
        turns = load_indexed_turns(run_dir)
        extractor = M2RuleFactExtractor()
        facts = extractor.extract_facts(
            schema=current_schema,
            turns=turns,
            meeting_metadata=meeting_metadata,
            run_id=run_dir.name,
        )
        _write_json(minutes_dir / "facts.json", [f.model_dump() for f in facts])

        # Re-render
        return self.update_facts_and_re_render(run_dir, [f.model_dump() for f in facts])
