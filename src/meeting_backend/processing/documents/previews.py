"""Repair derived page previews without regenerating or changing document content."""

import fcntl
import shutil

from meeting_backend.core.errors import AppError
from meeting_backend.infrastructure.artifacts.store import ArtifactStore
from meeting_backend.infrastructure.mongodb.client import new_id, now
from meeting_pipeline.minutes.visual_qa import render_document_pages


def pages_available(store, version):
    pages = version.get("previews", [])
    if not pages:
        return False
    for page in pages:
        record = store.mongo.db.artifacts.find_one({"_id": page["id"]})
        if not record:
            return False
        try:
            store.resolve(record)
        except AppError:
            return False
    return True


def repair_previews(mongo, *, apply=False):
    """Scan all versions; publish only derived PNGs and their display metadata.

    DOCX, facts, version IDs, review status and existing ZIP/manifests stay intact.
    Use the worker's filesystem lock to avoid parallel rendering/repair runs.
    """
    store = ArtifactStore(mongo)
    results = []
    with (store.root / ".worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise AppError(
                "PREVIEW_REPAIR_BUSY", "Worker đang xử lý. Hãy đợi hoặc dừng worker trước.", 409
            ) from exc
        for collection, document_key, parent_key in [
            ("template_versions", "normalized", "template_id"),
            ("minutes_versions", "docx", "meeting_id"),
        ]:
            for version in mongo.db[collection].find():
                if pages_available(store, version):
                    continue
                entry = {"collection": collection, "version_id": version["_id"]}
                results.append(entry)
                if not apply:
                    entry["status"] = "needs_preview"
                    continue
                destination = store.root / "previews" / version["_id"] / new_id()
                registered = []
                published = False
                try:
                    source_id = version[document_key]["id"]
                    source = mongo.db.artifacts.find_one(
                        {"_id": source_id, "owner_id": version["owner_id"]}
                    )
                    if not source:
                        raise AppError(
                            "ARTIFACT_MISSING", "Không tìm thấy DOCX của phiên bản.", 404
                        )
                    pages = render_document_pages(store.resolve(source), destination)
                    for page in pages:
                        registered.append(
                            store.register(
                                page,
                                version["owner_id"],
                                resource_id=version[parent_key],
                                visibility=source.get("visibility", "private"),
                            )
                        )
                    timestamp = now()
                    changes = {
                        "previews": [store.view(page) for page in registered],
                        "preview_repaired_at": timestamp,
                    }
                    report_key = "report" if collection == "template_versions" else "formatting"
                    report = dict(version.get(report_key) or {})
                    report.pop("preview_error", None)
                    if collection == "minutes_versions":
                        report.update(
                            {
                                "preview_scope": "all_pages",
                                "preview_pages": [
                                    str(page.relative_to(store.root)) for page in pages
                                ],
                                "preview_path_base": "application_data_dir",
                            }
                        )
                    changes[report_key] = report
                    result = mongo.db[collection].update_one(
                        {"_id": version["_id"], f"{document_key}.id": source_id},
                        {"$set": changes},
                    )
                    if not result.matched_count:
                        raise AppError("REVISION_CONFLICT", "Phiên bản đã thay đổi.", 409)
                    published = True
                    mongo.audit(
                        "maintenance",
                        "document_preview_repaired",
                        version["_id"],
                        collection=collection,
                        pages=len(pages),
                    )
                    entry.update(status="repaired", pages=len(pages))
                except Exception as exc:
                    if not published:
                        mongo.db.artifacts.delete_many(
                            {"_id": {"$in": [page["_id"] for page in registered]}}
                        )
                        shutil.rmtree(destination, ignore_errors=True)
                    entry.update(status="failed", error=str(exc))
        fcntl.flock(lock, fcntl.LOCK_UN)
    return {
        "database": mongo.settings.mongo_database,
        "dry_run": not apply,
        "versions": results,
        "repaired": sum(row["status"] == "repaired" for row in results),
        "failed": sum(row["status"] == "failed" for row in results),
    }
