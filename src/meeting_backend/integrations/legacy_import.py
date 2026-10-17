"""Read-only inspection and idempotent imports from legacy SQLite/JSON runs."""

import hashlib
import json
import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pymongo.errors import DuplicateKeyError

from meeting_backend.infrastructure.mongodb.client import new_id, now


def inspect_run(source):
    from meeting_backend.integrations.minutes_pipeline import validate_export

    source = Path(source).resolve()
    timeline = json.loads((source / "timeline.json").read_text())
    rows = timeline.get("segments")
    if not isinstance(rows, list):
        raise ValueError("Timeline phải có danh sách segments.")
    ids = [r.get("turn_id") for r in rows if r.get("turn_id")]
    if len(set(ids)) != len(ids):
        raise ValueError("Timeline có turn_id trùng.")
    for row in rows:
        if float(row.get("end_sec", 0)) < float(row.get("start_sec", 0)):
            raise ValueError("Mốc kết thúc đoạn sớm hơn mốc bắt đầu.")
    if (source / "exports/completed.docx").is_file():
        validate_export(source)
    digest = hashlib.sha256()
    hashes = {}
    total = 0
    for path in sorted(p for p in source.rglob("*") if p.is_file() and p.name != ".DS_Store"):
        file_hash = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                file_hash.update(chunk)
        relative = path.relative_to(source).as_posix()
        hashes[relative] = file_hash.hexdigest()
        digest.update(relative.encode() + b"\0" + file_hash.digest())
        total += path.stat().st_size
    return {
        "source": str(source),
        "fingerprint": digest.hexdigest(),
        "segments": len(rows),
        "file_count": len(hashes),
        "size_bytes": total,
        "hashes": hashes,
        "has_minutes": (source / "exports/completed.docx").is_file(),
    }


def import_run(mongo, username, source, *, dry_run=False, legacy_metadata=None):
    report = inspect_run(source)
    user = mongo.db.users.find_one({"username": username.lower(), "active": True})
    if not user:
        raise ValueError("Tài khoản nhận dữ liệu không tồn tại hoặc bị khóa.")
    existing = mongo.db.meetings.find_one(
        {"owner_id": user["_id"], "legacy_fingerprint": report["fingerprint"]}
    )
    if dry_run:
        return {
            **report,
            "existing_meeting_id": existing["_id"] if existing else None,
            "dry_run": True,
        }
    if existing:
        return existing["_id"]
    lock_id = (
        "legacy-import-"
        + hashlib.sha256((user["_id"] + report["fingerprint"]).encode()).hexdigest()
    )
    mongo.db.settings.delete_one({"_id": lock_id, "expires_at": {"$lt": datetime.now(UTC)}})
    try:
        mongo.db.settings.insert_one(
            {"_id": lock_id, "expires_at": datetime.now(UTC) + timedelta(hours=1)}
        )
    except DuplicateKeyError as exc:
        raise ValueError(
            "Bản nhập này đang được thực hiện. Hãy đợi hoặc kiểm tra khóa nhập trong settings."
        ) from exc
    created_ids = []
    try:
        mid = _copy_run(mongo, username, Path(source).resolve(), on_created=created_ids.append)
        directory = mongo.settings.data_dir / "imported" / mid
        copied = inspect_run(directory)
        if copied["hashes"] != report["hashes"]:
            raise ValueError("Hash file sau khi sao chép không khớp nguồn.")
        (directory / "import_manifest.json").write_text(
            json.dumps({**report, "legacy_metadata": legacy_metadata}, ensure_ascii=False, indent=2)
        )
        changes = {
            "legacy_fingerprint": report["fingerprint"],
            "legacy_source": str(source),
            "legacy_metadata": legacy_metadata or {},
        }
        if legacy_metadata and legacy_metadata.get("meeting_name"):
            changes["title"] = legacy_metadata["meeting_name"][:200]
        mongo.db.meetings.update_one({"_id": mid}, {"$set": changes})
        return mid
    except BaseException:
        # Only clean records belonging to this copy directory, never another import/user.
        for row in mongo.db.meetings.find({"owner_id": user["_id"], "_id": {"$in": created_ids}}):
            directory = mongo.settings.data_dir / "imported" / row["_id"]
            if row.get("legacy_fingerprint"):
                continue
            artifact_ids = [
                a["_id"]
                for a in mongo.db.artifacts.find(
                    {"path": {"$regex": "^imported/" + row["_id"] + "/"}}
                )
            ]
            templates = list(
                mongo.db.templates.find(
                    {"owner_id": user["_id"], "input_artifact_id": {"$in": artifact_ids}}
                )
            )
            for template in templates:
                mongo.db.template_versions.delete_many({"template_id": template["_id"]})
                mongo.db.templates.delete_one({"_id": template["_id"]})
            for name in [
                "transcript_versions",
                "transcript_segments",
                "minutes_versions",
                "sources",
            ]:
                mongo.db[name].delete_many({"meeting_id": row["_id"]})
            mongo.db.artifacts.delete_many({"path": {"$regex": "^imported/" + row["_id"] + "/"}})
            mongo.db.meetings.delete_one({"_id": row["_id"]})
            shutil.rmtree(directory, ignore_errors=True)
        raise
    finally:
        mongo.db.settings.delete_one({"_id": lock_id})


def import_legacy(mongo, username, root, *, sqlite_path=None, dry_run=False):
    """Use SQLite names/run IDs as metadata; artifact snapshots are the import source."""
    metadata = {}
    if sqlite_path:
        with sqlite3.connect(
            Path(sqlite_path).resolve().as_uri() + "?mode=ro", uri=True
        ) as connection:
            connection.row_factory = sqlite3.Row
            names = {r["id"]: r["name"] for r in connection.execute("SELECT id,name FROM meetings")}
            for row in connection.execute("SELECT id,meeting_id,status FROM runs"):
                metadata[row["id"]] = {
                    "run_id": row["id"],
                    "meeting_id": row["meeting_id"],
                    "meeting_name": names.get(row["meeting_id"]),
                    "run_status": row["status"],
                }
    result = []
    for timeline in sorted(Path(root).rglob("timeline.json")):
        try:
            result.append(
                {
                    "source": str(timeline.parent),
                    "result": import_run(
                        mongo,
                        username,
                        timeline.parent,
                        dry_run=dry_run,
                        legacy_metadata=metadata.get(timeline.parent.name),
                    ),
                }
            )
        except (ValueError, OSError, KeyError) as exc:
            result.append({"source": str(timeline.parent), "error": str(exc)})
    return {"dry_run": dry_run, "runs": result, "count": len(result)}


def _copy_run(mongo, username, source, *, on_created):
    """Copy a legacy run; never modify its source or reuse its SQLite database."""
    from types import SimpleNamespace

    from meeting_backend.infrastructure.artifacts.store import ArtifactStore
    from meeting_backend.integrations.audio_pipeline import normalize_segments
    from meeting_backend.integrations.minutes_pipeline import read_json, validate_export
    from meeting_backend.modules.meetings.schemas import MeetingCreate
    from meeting_backend.modules.meetings.service import create
    from meeting_backend.modules.transcripts.service import create_version

    user = mongo.db.users.find_one({"username": username.lower(), "active": True})
    if not user:
        raise ValueError("Hãy tạo tài khoản từ trang thiết lập trước khi nhập demo.")
    if not (source / "timeline.json").is_file():
        raise ValueError("Thư mục phải có timeline.json.")
    meeting = create(mongo, user, MeetingCreate(title="Cuộc họp mẫu · nhập từ demo"))
    mid = meeting["id"]
    on_created(mid)
    destination = mongo.settings.data_dir / "imported" / mid
    shutil.copytree(source, destination)
    store = ArtifactStore(mongo)
    context = SimpleNamespace(store=store, mongo=mongo)
    context.artifact = lambda path, **kwargs: store.view(
        store.register(path, user["_id"], resource_id=mid, **kwargs)
    )
    original = mongo.db.meetings.find_one({"_id": mid})
    rows = read_json(destination / "timeline.json").get("segments", [])
    # Remove paths that belonged to the former checkout; local relative clips are re-registered.
    for row in rows:
        for key in ["evidence_clip_artifact_id", "processed_clip_artifact_id"]:
            value = row.get(key)
            if value and Path(value).is_absolute():
                absolute = Path(value).resolve()
                candidate = (
                    destination / absolute.relative_to(source)
                    if absolute.is_relative_to(source)
                    else destination / Path(value).name
                )
                row[key] = str(candidate) if candidate.is_file() else None
    transcript = create_version(
        mongo,
        original,
        normalize_segments(context, destination, rows),
        reason="Nhập demo cũ",
        run_path=str(destination),
    )
    updates = {
        "active_transcript_id": transcript["_id"],
        "content_revision": 1,
        "revision": 2,
        "state": "transcript_ready",
        "updated_at": now(),
    }
    normalized = destination / "template/normalized.docx"
    if not normalized.is_file():
        candidates = list((destination / "template").glob("*.docx"))
        normalized = candidates[0] if candidates else normalized
    if normalized.is_file():
        from docx import Document

        from meeting_backend.processing.documents.ingest import paragraphs

        tid, tvid = new_id(), new_id()
        schema = read_json(destination / "template/schema.json")
        template = {
            "_id": tid,
            "owner_id": user["_id"],
            "name": "Mẫu biên bản demo",
            "visibility": "private",
            "state": "ready",
            "active_version_id": tvid,
            "revision": 1,
            "active_job": None,
            "trashed": False,
            "needs_review": False,
            "created_at": now(),
            "updated_at": now(),
            "field_count": len(schema.get("fields", [])),
        }
        artifact = store.register(normalized, user["_id"], resource_id=tid)
        template["input_artifact_id"] = artifact["_id"]
        mongo.db.templates.insert_one(template)
        view = store.view(artifact)
        mongo.db.template_versions.insert_one(
            {
                "_id": tvid,
                "owner_id": user["_id"],
                "template_id": tid,
                "created_at": now(),
                "normalized": view,
                "original": view,
                "schema": schema,
                "report": {"engine": "legacy_import", "needs_review": False, "warnings": []},
                "previews": [],
                "paragraphs": [
                    {"index": i, "text": p.text}
                    for i, p in enumerate(paragraphs(Document(normalized)))
                ],
            }
        )
        if (destination / "exports/completed.docx").is_file():
            validate_export(destination)
            vid = new_id()
            version = {
                "_id": vid,
                "owner_id": user["_id"],
                "meeting_id": mid,
                "created_at": now(),
                "reason": "legacy_import",
                "input_content_revision": 1,
                "transcript_version_id": transcript["_id"],
                "template_id": tid,
                "template_version_id": tvid,
                "run_path": str(destination),
                "parent_id": None,
                "facts": read_json(destination / "minutes/facts.json", []),
                "schema": schema,
                "options": read_json(destination / "minutes/configuration.json"),
                "formatting": read_json(destination / "minutes/formatting_report.json"),
                "report": read_json(destination / "minutes/model_report.json"),
                "topics": read_json(destination / "minutes/topics.json"),
                "corrections": read_json(destination / "minutes/corrections.json", []),
                "manifest": read_json(destination / "minutes/manifest.json"),
                "docx": context.artifact(destination / "exports/completed.docx"),
                "zip": context.artifact(destination / "exports/completed_minutes.zip"),
                "previews": [
                    context.artifact(p)
                    for p in sorted((destination / "exports/minutes_preview").glob("page-*.png"))
                ],
            }
            mongo.db.minutes_versions.insert_one(version)
            updates.update(active_minutes_id=vid, state="minutes_ready")
    mongo.db.meetings.update_one({"_id": mid}, {"$set": updates})
    mongo.audit(user["_id"], "legacy_run_imported", mid)
    return mid
