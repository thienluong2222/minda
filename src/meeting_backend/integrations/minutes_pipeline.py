"""Materialize immutable inputs, reuse the Word pipeline, publish complete document versions."""

import json
import shutil
from pathlib import Path

from meeting_backend.core.errors import AppError
from meeting_backend.infrastructure.mongodb.client import new_id, now
from meeting_backend.modules.transcripts.service import rows_for


def read_json(path, default=None):
    return json.loads(path.read_text()) if path.is_file() else ({} if default is None else default)


def copy_document_run(source, destination):
    destination.mkdir(parents=True, exist_ok=True)
    for name in ["template", "minutes", "exports"]:
        path = source / name
        if path.is_dir():
            shutil.copytree(path, destination / name, dirs_exist_ok=True)
    for name in ["timeline.json", "manifest.json"]:
        if (source / name).is_file():
            shutil.copy2(source / name, destination / name)


def materialize_transcript(context, meeting, run):
    payload = context.job.get("payload", {})
    snapshot_id = payload.get("input_snapshot_id")
    if snapshot_id:
        from meeting_pipeline.minutes.graph_contracts import digest

        snapshot = context.mongo.db.minutes_input_snapshots.find_one(
            {
                "_id": snapshot_id,
                "owner_id": meeting["owner_id"],
                "meeting_id": meeting["_id"],
            }
        )
        if not snapshot:
            raise AppError("INPUT_SNAPSHOT_MISSING", "Thiếu phiên bản đầu vào đã chốt.")
        records = context.mongo.db.minutes_input_segments.find(
            {
                "snapshot_id": snapshot_id,
                "owner_id": meeting["owner_id"],
                "meeting_id": meeting["_id"],
            }
        ).sort("index", 1)
        rows = [record["segment"] for record in records]
        if len(rows) != snapshot["row_count"] or digest(rows) != snapshot["source_sha256"]:
            raise AppError(
                "INPUT_SNAPSHOT_INVALID", "Đầu vào đã chốt không khớp kiểm tra toàn vẹn."
            )
    else:
        rows = rows_for(
            context.mongo, payload.get("transcript_version_id", meeting["active_transcript_id"])
        )
    data = []
    for row in rows:
        item = dict(row.get("data", {}))
        if not item.get("turn_id"):
            item["turn_id"] = row["_id"]
        item.update(
            text=row.get("text", ""),
            speaker_label=row.get("speaker_label", ""),
            start_sec=row["start_sec"],
            end_sec=row["end_sec"],
        )
        if row.get("user_edited"):
            item["user_edited"] = True
        # The original audio artifacts remain immutable and owned by this meeting.
        if row.get("clip"):
            artifact = context.mongo.db.artifacts.find_one(
                {
                    "_id": row["clip"]["id"],
                    "resource_id": meeting["_id"],
                    "owner_id": meeting["owner_id"],
                }
            )
            if artifact:
                item["evidence_clip_artifact_id"] = str(context.store.resolve(artifact))
                item["clip_artifact_id"] = artifact["_id"]
        data.append(item)
    (run / "timeline.json").write_text(json.dumps({"segments": data}, ensure_ascii=False, indent=2))


def validate_export(run):
    import hashlib
    import zipfile

    from docx import Document

    path = run / "exports/completed.docx"
    Document(path)
    manifest = read_json(run / "minutes/manifest.json")
    blob = path.read_bytes()
    if hashlib.sha256(blob).hexdigest() != manifest["completed_docx_sha256"]:
        raise RuntimeError("Manifest không khớp DOCX.")
    with zipfile.ZipFile(run / "exports/completed_minutes.zip") as archive:
        if (
            archive.testzip()
            or archive.read("completed.docx") != blob
            or json.loads(archive.read("manifest.json")) != manifest
        ):
            raise RuntimeError("ZIP không khớp DOCX.")


def stamp_export_context(run, **context):
    """Publish application IDs even when the core consumed a staging/legacy run."""
    import zipfile

    path = run / "minutes/manifest.json"
    manifest = read_json(path)
    manifest.update(run_id=context["job_id"], meeting_id=context["meeting_id"], app_context=context)
    blob = json.dumps(manifest, ensure_ascii=False, indent=2).encode()
    path.write_bytes(blob)
    package = run / "exports/completed_minutes.zip"
    temporary = package.with_suffix(".zip.tmp")
    with (
        zipfile.ZipFile(package) as source,
        zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        for info in source.infolist():
            if info.filename == "manifest.json":
                continue
            with (
                source.open(info) as reader,
                target.open(info.filename, "w", force_zip64=True) as writer,
            ):
                shutil.copyfileobj(reader, writer, length=1024 * 1024)
        target.writestr("manifest.json", blob)
    temporary.replace(package)


def reconcile_regenerated_facts(old, generated, schema, *, unchanged_input):
    """Carry edits only across identical fields and provenance."""
    old_fields = {field["field_id"]: field for field in old.get("schema", {}).get("fields", [])}
    same_fields = {
        field["field_id"]
        for field in schema["fields"]
        if field == old_fields.get(field["field_id"])
    }
    previous = {fact["field_id"]: fact for fact in old.get("facts", [])}
    result = []
    for fact in generated:
        field_id = fact["field_id"]
        prior = previous.get(field_id, {})
        pending = prior.get("previous_edit")
        if field_id not in same_fields or (not prior.get("user_edited") and pending is None):
            result.append(fact)
            continue
        if unchanged_input and prior.get("user_edited"):
            result.append(prior)
            continue
        prior_value = pending["value"] if pending is not None else prior["value"]
        if prior_value == fact["value"] and fact["status"] == "supported":
            result.append(fact)
            continue
        result.append(
            {
                **fact,
                "status": "conflicting" if prior_value != fact["value"] else "needs_review",
                "previous_edit": {
                    "value": prior_value,
                    "minutes_version_id": (
                        pending["minutes_version_id"] if pending is not None else old["_id"]
                    ),
                },
            }
        )
    return result


def run_minutes(context):
    context.stage("Chuẩn bị phiên bản biên bản và transcript đầu vào")
    meeting = context.resource()
    kind = context.job["kind"]
    payload = context.job.get("payload", {})
    if kind == "generate_minutes":
        transcript = context.mongo.db.transcript_versions.find_one(
            {
                "_id": payload.get("transcript_version_id", meeting.get("active_transcript_id")),
                "meeting_id": meeting["_id"],
            }
        )
        if transcript and transcript.get("timing_complete") is False:
            raise AppError("TIMELINE_REVIEW_REQUIRED", "Hãy rà các đồng hồ chưa căn trước.", 409)
    from meeting_pipeline.minutes.service import MinutesService
    from meeting_pipeline.minutes.text_engine import MinutesOptions

    old = context.mongo.db.minutes_versions.find_one({"_id": meeting.get("active_minutes_id")})
    source = old
    if kind == "revise_minutes_outline" and (
        not source
        or source["_id"] != payload["version_id"]
        or source["transcript_version_id"] != meeting.get("active_transcript_id")
        or source["input_content_revision"] != meeting.get("content_revision")
    ):
        raise AppError("OUTLINE_STALE", "Biên bản hoặc lời chép đã thay đổi.", 409)
    if kind == "restore_minutes":
        source = context.mongo.db.minutes_versions.find_one(
            {"_id": payload["version_id"], "meeting_id": meeting["_id"]}
        )
    run = context.staging / meeting["_id"] / "runs" / context.job["_id"]
    if source and kind != "generate_minutes":
        old_path = Path(source["run_path"]).resolve()
        if not old_path.is_relative_to(context.store.root):
            raise AppError("INVALID_PATH", "Phiên bản nguồn không hợp lệ.")
        copy_document_run(old_path, run)
    else:
        run.mkdir(parents=True)
    service = MinutesService()
    input_revision = (
        context.job["input_content_revision"]
        if kind == "generate_minutes"
        else source["input_content_revision"]
    )
    template_id = (
        payload.get("template_id") if kind == "generate_minutes" else source["template_id"]
    )
    template_version_id = (
        payload.get("template_version_id")
        if kind == "generate_minutes"
        else source.get("template_version_id")
    )
    if kind == "generate_minutes":
        template = context.mongo.db.template_versions.find_one(
            {"_id": template_version_id, "template_id": template_id}
        )
        parent = context.mongo.db.templates.find_one({"_id": template_id, "trashed": False})
        if (
            not template
            or not parent
            or (parent["owner_id"] != meeting["owner_id"] and parent.get("visibility") != "shared")
        ):
            raise AppError(
                "INVALID_TEMPLATE", "Mẫu không còn sẵn sàng hoặc đã đổi quyền truy cập.", 422
            )
        template_artifact = context.mongo.db.artifacts.find_one(
            {"_id": template["normalized"]["id"]}
        )
        normalized = context.store.resolve(template_artifact)
        (run / "template").mkdir(exist_ok=True)
        (run / "template/schema.json").write_text(
            json.dumps(template["schema"], ensure_ascii=False, indent=2)
        )
        materialize_transcript(context, meeting, run)
        effective_options = dict(payload["options"])
        # Jobs queued before this feature retain their original engine.
        effective_options.setdefault("graph_enabled", False)
        options = MinutesOptions.model_validate(effective_options)
        metadata = payload.get("metadata_snapshot") or {
            "meeting_name": meeting["title"],
            "meeting_date": meeting.get("date", ""),
            "location": meeting.get("location", ""),
        }
        context.stage("Trích xuất thông tin, biên tập và định dạng biên bản")
        service.process_template_for_run(
            normalized, run, meeting_metadata=metadata, options=options, reuse_schema=True
        )
        if old and old.get("template_version_id") == template_version_id:
            generated = read_json(run / "minutes/facts.json", [])
            reconciled = reconcile_regenerated_facts(
                old,
                generated,
                read_json(run / "template/schema.json"),
                unchanged_input=(
                    old.get("transcript_version_id") == meeting["active_transcript_id"]
                    and old.get("input_content_revision") == input_revision
                ),
            )
            if reconciled != generated:
                service.update_facts_and_re_render(run, reconciled, mark_user_edited=False)
    elif kind == "edit_facts":
        context.stage("Ghép các trường đã sửa, giữ bằng chứng và cập nhật tài liệu")
        service.update_facts_and_re_render(run, payload["patches"])
    elif kind == "revise_minutes_outline":
        from meeting_backend.modules.minutes.outline_revision import regenerate_outline

        context.stage("Viết và kiểm tra các mục đã chỉnh trong dàn ý")
        regenerate_outline(run, payload, source, service)
    elif kind == "format_minutes":
        context.stage("Áp dụng thể thức từ dữ liệu đã lưu")
        service.reformat_existing(run, MinutesOptions.model_validate(payload["options"]))
    elif kind == "restore_minutes":
        context.stage("Khôi phục nội dung đã chọn thành phiên bản mới")
    else:
        raise ValueError("Loại tác vụ biên bản không hợp lệ.")
    context.check()
    context.stage("Kiểm tra DOCX, preview, manifest và ZIP")
    stamp_export_context(
        run,
        meeting_id=meeting["_id"],
        job_id=context.job["_id"],
        transcript_version_id=meeting.get("active_transcript_id")
        if kind == "generate_minutes"
        else source.get("transcript_version_id"),
        input_content_revision=input_revision,
        template_id=template_id,
        template_version_id=template_version_id,
        source_minutes_version_id=source["_id"] if source else None,
    )
    validate_export(run)
    final = context.root / "document_versions" / meeting["_id"] / context.job["_id"]
    final.parent.mkdir(parents=True, exist_ok=True)
    if final.exists():
        raise RuntimeError("Thư mục phiên bản đã tồn tại.")
    shutil.move(str(run), final)
    version_id = new_id()
    previews = []
    for path in sorted(
        (final / "exports/minutes_preview").glob("page-*.png"),
        key=lambda p: int(p.stem.split("-")[-1]),
    ):
        previews.append(context.artifact(path))
    version = {
        "_id": version_id,
        "owner_id": meeting["owner_id"],
        "meeting_id": meeting["_id"],
        "created_at": now(),
        "parent_id": meeting.get("active_minutes_id"),
        "reason": kind,
        "input_content_revision": input_revision,
        "transcript_version_id": payload.get(
            "transcript_version_id", meeting.get("active_transcript_id")
        )
        if kind == "generate_minutes"
        else source.get("transcript_version_id"),
        "template_id": template_id,
        "template_version_id": template_version_id,
        "run_path": str(final),
        "facts": read_json(final / "minutes/facts.json", []),
        "schema": read_json(final / "template/schema.json"),
        "options": read_json(final / "minutes/configuration.json"),
        "report": read_json(final / "minutes/model_report.json"),
        "formatting": read_json(final / "minutes/formatting_report.json"),
        "topics": read_json(final / "minutes/topics.json"),
        "corrections": read_json(final / "minutes/corrections.json", []),
        "graph_id": read_json(final / "minutes/model_report.json").get("graph_id"),
        "style_profile": read_json(final / "minutes/style_profile.json"),
        "manifest": read_json(final / "minutes/manifest.json"),
        "previews": previews,
        "docx": context.artifact(final / "exports/completed.docx", name=meeting["title"] + ".docx"),
        "zip": context.artifact(
            final / "exports/completed_minutes.zip", name=meeting["title"] + ".zip"
        ),
    }
    graph_payload = read_json(final / "minutes/meeting_graph.json")
    if graph_payload:
        from meeting_backend.modules.minutes.graph_store import persist_graph

        persist_graph(context.mongo, meeting, graph_payload)
    from meeting_backend.modules.minutes.outline_store import persist_outline

    version["outline"] = persist_outline(
        context.mongo, meeting, version_id, read_json(final / "minutes/content_plan.json")
    )
    context.mongo.db.minutes_versions.insert_one(version)
    stale = input_revision != meeting.get("content_revision", 0)
    context.publish(
        {
            "active_minutes_id": version_id,
            "minutes_stale": stale,
            "state": "minutes_ready",
            "reviewed_version": None,
            "reviewed_at": None,
        },
        result={"minutes_version_id": version_id},
    )
