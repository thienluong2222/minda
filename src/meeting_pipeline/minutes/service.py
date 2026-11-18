"""Minutes service orchestrating normalization, schema mapping,
fact extraction, rendering, and export.

Specification: Section 3, 5 (F0-F5), and 7 of docs/PLAN_BIEU_MAU_BIEN_BAN_V1.md.
"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

from meeting_pipeline.minutes.converter import compute_file_sha256, normalize_template
from meeting_pipeline.minutes.doc_parser import parse_template_document
from meeting_pipeline.minutes.document_formatting import format_minutes_document
from meeting_pipeline.minutes.evidence_retrieval import load_indexed_turns
from meeting_pipeline.minutes.fact_edits import merge_fact_edits
from meeting_pipeline.minutes.graph_export import guard_graph_export
from meeting_pipeline.minutes.manifest import generate_minutes_manifest, save_minutes_manifest
from meeting_pipeline.minutes.meeting_record import build_meeting_record
from meeting_pipeline.minutes.model_pipeline import run_text_models
from meeting_pipeline.minutes.model_runtime import ModelRuntimeError, model_status
from meeting_pipeline.minutes.renderer import render_completed_document
from meeting_pipeline.minutes.schema_mapper import (
    M0RuleSchemaMapper,
    SchemaValidator,
    load_schema,
    reconcile_schema_structure,
    save_schema,
)
from meeting_pipeline.minutes.schemas import (
    DocGraph,
    MeetingFact,
    RunMetrics,
    TemplateField,
)
from meeting_pipeline.minutes.structured_fields import structured_facts
from meeting_pipeline.minutes.text_engine import MinutesOptions
from meeting_pipeline.minutes.transactions import GENERATION_LOCK, minutes_transaction
from meeting_pipeline.minutes.visual_qa import render_document_pages, render_document_to_image

logger = logging.getLogger(__name__)


def _write_json(path: Path, data: Any) -> None:
    """Safely write JSON file with parent directory creation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _format_export(
    run_dir: Path, options: MinutesOptions, conversion: dict[str, Any] | None = None
) -> dict[str, Any]:
    path = run_dir / "exports/completed.docx"
    people: dict[str, str] = {}
    facts_path = run_dir / "minutes/facts.json"
    facts = json.loads(facts_path.read_text()) if facts_path.is_file() else []
    for role, prefix in (("chair", "chairperson_name"), ("secretary", "secretary_name")):
        values = {
            f["value"]
            for f in facts
            if f["field_id"].startswith(prefix)
            and f["status"] == "supported"
            and isinstance(f.get("value"), str)
            and f["value"].strip()
        }
        if len(values) == 1:
            people[role] = values.pop()
    report = format_minutes_document(
        path,
        options.format_standard,
        options.document_metadata,
        options.two_sided,
        grounded_people=people,
    )
    previous_path = run_dir / "minutes/formatting_report.json"
    previous = json.loads(previous_path.read_text()) if previous_path.is_file() else {}
    report["conversion"] = conversion if conversion is not None else previous.get("conversion", {})
    for warning in report["conversion"].get("warnings", []):
        report["review_items"].append({"code": "doc_conversion", "message": warning})
        report["status"] = "needs_review"
    report["preview_pages"] = []
    try:
        pages = render_document_pages(path, run_dir / "exports/minutes_preview")
        report["preview_pages"] = [str(p.relative_to(run_dir)) for p in pages]
        report["preview_scope"] = "all_pages"
        shutil.copy2(pages[0], run_dir / "exports/preview_after.png")
    except Exception as exc:
        report["preview_scope"] = "unavailable"
        report["preview_error"] = str(exc)
        logger.warning("Full-page minutes preview unavailable: %s", exc)
        try:
            render_document_to_image(path, run_dir / "exports", "preview_after.png")
            report["preview_scope"] = "thumbnail_only"
        except Exception:
            (run_dir / "exports/preview_after.png").unlink(missing_ok=True)
    _write_json(run_dir / "minutes/formatting_report.json", report)
    return report


class MinutesService:
    """Orchestrates end-to-end meeting minutes generation from audio runs and Word templates."""

    def process_template_for_run(
        self,
        template_file_path: Path,
        run_dir: Path,
        meeting_metadata: dict[str, Any] | None = None,
        use_model: bool = False,
        options: MinutesOptions | None = None,
        reuse_schema: bool = False,
    ) -> dict[str, Any]:
        """Rollback document artifacts if inference fails; never touch timeline/audio."""
        if not GENERATION_LOCK.acquire(blocking=False):
            raise ModelRuntimeError("Một biên bản đang được tạo. Hãy thử lại khi hoàn thành.")
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".minutes-backup-", dir=run_dir) as temp:
                backup = Path(temp)
                names = [
                    "template",
                    "minutes",
                    "exports/completed.docx",
                    "exports/completed_minutes.zip",
                    "exports/preview_after.png",
                    "exports/minutes_preview",
                ]
                for name in names:
                    src, dst = run_dir / name, backup / name
                    if src.is_dir():
                        shutil.copytree(src, dst)
                    elif src.is_file():
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dst)
                try:
                    return self._process_template_for_run(
                        template_file_path,
                        run_dir,
                        meeting_metadata,
                        use_model,
                        options,
                        reuse_schema,
                    )
                except BaseException:
                    log = run_dir / "minutes/model_runtime.log"
                    if log.is_file():
                        shutil.copy2(log, run_dir / "minutes_failed.log")
                    for name in names:
                        dst, src = run_dir / name, backup / name
                        if dst.is_dir():
                            shutil.rmtree(dst)
                        elif dst.is_file():
                            dst.unlink()
                        if src.is_dir():
                            shutil.copytree(src, dst)
                        elif src.is_file():
                            dst.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(src, dst)
                    raise
        finally:
            GENERATION_LOCK.release()

    def _process_template_for_run(
        self,
        template_file_path: Path,
        run_dir: Path,
        meeting_metadata: dict[str, Any] | None = None,
        use_model: bool = False,
        options: MinutesOptions | None = None,
        reuse_schema: bool = False,
    ) -> dict[str, Any]:
        """Execute full minutes pipeline from uploaded template to completed.docx and manifest."""
        t_start = time.perf_counter()
        options = options or MinutesOptions(use_model=use_model)
        if options.two_sided and options.format_standard != "hd05_2026":
            raise ValueError("Lề in hai mặt hiện áp dụng cho thể thức Đảng theo Hướng dẫn 05.")
        if options.use_model:
            availability = model_status()
            if not all(
                availability[k] for k in ("runtime_available", "model_cached", "embedding_cached")
            ):
                raise ModelRuntimeError("Runtime/model chưa sẵn sàng. Xem docs/LLM_FCM_MINUTES.md.")
        elif options.mode == "general":
            raise ValueError("Chế độ tổng quát cần bật LLM để phân nhóm và biên tập nội dung.")
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
        if template_file_path.resolve() != orig_copy.resolve():
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
        if reuse_schema and (template_dir / "schema.json").is_file():
            proposed_schema = load_schema(template_dir / "schema.json")

        proposed_schema = reconcile_schema_structure(proposed_schema, doc_graph)
        m1_status = "not_run"

        save_schema(proposed_schema, template_dir / "schema_proposal.json")
        save_schema(proposed_schema, template_dir / "schema.json")
        metrics.schema_proposal_sec = round(time.perf_counter() - t0, 4)
        metrics.field_count = len(proposed_schema.fields)

        # 4. Load audio timeline turns & retrieve evidence
        t0 = time.perf_counter()
        turns = load_indexed_turns(run_dir)
        _write_json(minutes_dir / "meeting_record.json", build_meeting_record(turns, run_dir.name))
        metrics.turn_count = len(turns)
        metrics.retrieval_sec = round(time.perf_counter() - t0, 4)

        # 5. Extract facts (M2 rule baseline + M3 model if enabled)
        t0 = time.perf_counter()
        facts = structured_facts(
            graph=doc_graph,
            schema=proposed_schema,
            turns=turns,
            meeting_metadata=meeting_metadata,
            run_id=run_dir.name,
            scoped_only=True,
        )

        m3_status = "not_run"
        model_report: dict[str, Any] = {}
        if options.use_model:
            proposed_schema, facts, model_report = run_text_models(
                proposed_schema,
                doc_graph,
                turns,
                run_dir,
                options,
                preserve_schema=reuse_schema and proposed_schema.proposed_by == "user_manual",
                meeting_metadata=meeting_metadata,
            )
            m1_status = "preserved" if reuse_schema else "success"
            m3_status = "needs_review" if model_report["warnings"] else "success"
            metrics.model_calls = len(model_report["calls"])
            save_schema(proposed_schema, template_dir / "schema.json")
            save_schema(proposed_schema, template_dir / "schema_proposal.json")
        else:
            _write_json(minutes_dir / "configuration.json", options.model_dump(mode="json"))
            for name in (
                "model_report.json",
                "corrections.json",
                "corrected_transcript.json",
                "topics.json",
                "meeting_graph.json",
                "content_plan.json",
                "content_plan_prepared.json",
                "verification.json",
                "coverage.json",
                "style_profile.json",
                "input_snapshot.json",
            ):
                (minutes_dir / name).unlink(missing_ok=True)

        # Preserve explicit human fact edits when rebuilding from the same template.
        if reuse_schema and (minutes_dir / "facts.json").is_file():
            previous = json.loads((minutes_dir / "facts.json").read_text())
            edited = {
                f["field_id"]: MeetingFact.model_validate(f)
                for f in previous
                if f.get("user_edited")
            }
            facts = [edited.get(f.field_id, f) for f in facts]

        facts = guard_graph_export(
            run_dir, proposed_schema, doc_graph, facts, turns, meeting_metadata
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
            general_content_field_id=model_report.get("body_field_id"),
        )
        formatting_report = _format_export(
            run_dir,
            options,
            {
                "input_format": converted.original_format,
                "engine": converted.conversion_engine,
                "warnings": list(converted.conversion_warnings),
            },
        )
        completed_sha = compute_file_sha256(completed_docx_path)
        metrics.render_sec = round(time.perf_counter() - t0, 4)

        # 7. Render before/after visual QA previews
        try:
            render_document_to_image(orig_copy, template_dir, "preview_before.png")
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
            models={
                "m0_schema": "rules",
                "m1_status": m1_status,
                "m2_facts": "rules",
                "m3_status": m3_status,
                "llm": str(model_report.get("model_id", "not_run")),
                "mode": options.mode,
                "format_standard": options.format_standard,
                "format_profile_version": formatting_report["profile_version"],
                "topic_clustering": "fuzzy_c_means"
                if options.use_model and options.mode == "general" and options.use_fcm
                else "not_run",
            },
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
            for name in (
                "meeting_record.json",
                "configuration.json",
                "formatting_report.json",
                "corrections.json",
                "corrected_transcript.json",
                "topics.json",
                "meeting_graph.json",
                "content_plan.json",
                "content_plan_prepared.json",
                "verification.json",
                "coverage.json",
                "style_profile.json",
                "input_snapshot.json",
                "model_report.json",
            ):
                if (minutes_dir / name).is_file():
                    zf.write(minutes_dir / name, name)

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
            "model_report": model_report,
            "formatting_report": formatting_report,
        }

    def regenerate(self, run_dir: Path, options: MinutesOptions) -> dict[str, Any]:
        originals = list((run_dir / "template").glob("original.*"))
        if not originals:
            raise FileNotFoundError("Hãy tải mẫu Word trước khi tạo lại biên bản.")
        return self.process_template_for_run(
            originals[0], run_dir, options=options, reuse_schema=True
        )

    def update_facts_and_re_render(
        self,
        run_dir: Path,
        updated_facts_data: list[dict[str, Any]],
        *,
        options: MinutesOptions | None = None,
        mark_user_edited: bool = True,
    ) -> Path:
        """Update facts with user edits and re-render document without re-running ASR."""
        with minutes_transaction(run_dir):
            return self._update_facts_and_re_render(
                run_dir, updated_facts_data, options, mark_user_edited
            )

    def reformat_existing(self, run_dir: Path, requested: MinutesOptions) -> Path:
        """Change presentation using saved facts; never load LLM/ASR or re-extract."""
        facts_path = run_dir / "minutes/facts.json"
        if not facts_path.is_file():
            raise FileNotFoundError("Hãy tải mẫu Word và tạo biên bản trước khi áp dụng thể thức.")
        config_path = run_dir / "minutes/configuration.json"
        previous = MinutesOptions.model_validate(
            json.loads(config_path.read_text()) if config_path.is_file() else {}
        )
        options = previous.model_copy(
            update={
                "format_standard": requested.format_standard,
                "document_metadata": requested.document_metadata,
                "two_sided": requested.two_sided,
            }
        )
        return self.update_facts_and_re_render(
            run_dir, json.loads(facts_path.read_text()), options=options, mark_user_edited=False
        )

    def _update_facts_and_re_render(
        self,
        run_dir: Path,
        updated_facts_data: list[dict[str, Any]],
        options: MinutesOptions | None,
        mark_user_edited: bool,
    ) -> Path:
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

        current_path = minutes_dir / "facts.json"
        current = [MeetingFact.model_validate(f) for f in json.loads(current_path.read_text())]
        facts = (
            merge_fact_edits(current, updated_facts_data)
            if mark_user_edited
            else [MeetingFact.model_validate(f) for f in updated_facts_data]
        )

        if (minutes_dir / "meeting_graph.json").is_file():
            facts = guard_graph_export(
                run_dir, schema, doc_graph, facts, load_indexed_turns(run_dir)
            )
        _write_json(minutes_dir / "facts.json", [f.model_dump() for f in facts])

        # Re-render
        completed_docx_path = exports_dir / "completed.docx"
        report_path = minutes_dir / "model_report.json"
        model_report = json.loads(report_path.read_text()) if report_path.is_file() else {}
        _, completed_sha = render_completed_document(
            normalized_docx_path=normalized_docx,
            output_docx_path=completed_docx_path,
            doc_graph=doc_graph,
            schema=schema,
            facts=facts,
            general_content_field_id=model_report.get("body_field_id"),
        )
        config_path = minutes_dir / "configuration.json"
        options = options or MinutesOptions.model_validate(
            json.loads(config_path.read_text()) if config_path.is_file() else {}
        )
        _write_json(config_path, options.model_dump(mode="json"))
        formatting_report = _format_export(run_dir, options)
        completed_sha = compute_file_sha256(completed_docx_path)

        # Re-save manifest
        manifest_path = minutes_dir / "manifest.json"
        previous_manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
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
            models={
                **previous_manifest.get("models", {}),
                "format_standard": options.format_standard,
                "format_profile_version": formatting_report["profile_version"],
            },
            timings=previous_manifest.get("timings", {}),
        )
        save_minutes_manifest(manifest, manifest_path)

        # Update ZIP
        zip_path = exports_dir / "completed_minutes.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(completed_docx_path, "completed.docx")
            zf.write(manifest_path, "manifest.json")
            zf.write(minutes_dir / "facts.json", "facts.json")
            zf.write(schema_path, "schema.json")
            for name in (
                "meeting_record.json",
                "configuration.json",
                "formatting_report.json",
                "corrections.json",
                "corrected_transcript.json",
                "topics.json",
                "meeting_graph.json",
                "content_plan.json",
                "content_plan_prepared.json",
                "verification.json",
                "coverage.json",
                "style_profile.json",
                "input_snapshot.json",
                "model_report.json",
                "timings.json",
            ):
                if (minutes_dir / name).is_file():
                    zf.write(minutes_dir / name, name)

        return completed_docx_path

    def update_schema_and_re_extract(
        self,
        run_dir: Path,
        updated_fields_data: list[dict[str, Any]],
        meeting_metadata: dict[str, Any] | None = None,
    ) -> Path:
        """Validate and publish the schema under the complete edit transaction."""
        with minutes_transaction(run_dir):
            return self._update_schema_and_re_extract(
                run_dir, updated_fields_data, meeting_metadata
            )

    def _update_schema_and_re_extract(
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
        facts = structured_facts(
            graph=doc_graph,
            schema=current_schema,
            turns=turns,
            meeting_metadata=meeting_metadata,
            run_id=run_dir.name,
            scoped_only=True,
        )
        _write_json(minutes_dir / "facts.json", [f.model_dump() for f in facts])

        # Re-render
        return self._update_facts_and_re_render(
            run_dir, [f.model_dump() for f in facts], None, False
        )
