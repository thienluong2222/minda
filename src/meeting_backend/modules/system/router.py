import re
import shutil

from fastapi import APIRouter, Depends, File, Query, UploadFile
from pymongo import ReturnDocument

from meeting_backend.api.dependencies import administrator, current_user, database
from meeting_backend.core.errors import AppError
from meeting_backend.infrastructure.artifacts.store import ArtifactStore
from meeting_backend.infrastructure.mongodb.client import now, public
from meeting_backend.modules.jobs.service import enqueue, job_view
from meeting_backend.modules.system import service
from meeting_backend.modules.system.schemas import Evaluation, Preset, RestoreBackup

router = APIRouter(tags=["system"])


@router.get("/capabilities")
def capabilities(user=Depends(current_user), mongo=Depends(database)):
    return service.capabilities(mongo)


@router.get("/dashboard")
def dashboard(user=Depends(current_user), mongo=Depends(database)):
    query = {"owner_id": user["_id"], "trashed": False}
    meetings = list(mongo.db.meetings.find(query).sort("updated_at", -1))
    ready = [m for m in meetings if m.get("active_minutes_id")]
    return {
        "counts": {
            "meetings": len(meetings),
            "processing": sum(bool(m.get("active_job")) for m in meetings),
            "minutes": len(ready),
            "needs_review": sum(
                bool(
                    m.get("minutes_stale")
                    or m.get("reviewed_version") != m.get("active_minutes_id")
                )
                for m in ready
            ),
        },
        "recent_meetings": [public(m) for m in meetings[:8]],
        "jobs": [
            job_view(j)
            for j in mongo.db.jobs.find(
                {
                    "owner_id": user["_id"],
                    "state": {"$in": ["queued", "running", "failed", "interrupted"]},
                }
            )
            .sort("created_at", -1)
            .limit(8)
        ],
    }


@router.get("/admin/overview")
def overview(user=Depends(administrator), mongo=Depends(database)):
    root = mongo.settings.data_dir
    root.mkdir(parents=True, exist_ok=True)
    disk = shutil.disk_usage(root)
    states = {
        state: mongo.db.jobs.count_documents({"state": state})
        for state in ["queued", "running", "failed", "interrupted", "succeeded", "cancelled"]
    }
    return {
        "users": mongo.db.users.count_documents({}),
        "meetings": mongo.db.meetings.count_documents({"trashed": False}),
        "jobs": states,
        "disk": {"free_bytes": disk.free, "total_bytes": disk.total},
        "capabilities": service.capabilities(mongo),
        "database": mongo.settings.mongo_database,
    }


def paged_records(collection, query, page, limit, legacy_limit):
    cursor = collection.find(query).sort([("created_at", -1), ("_id", 1)])
    if page is None:
        return [public(record) for record in cursor.limit(legacy_limit)]
    return {
        "items": [public(record) for record in cursor.skip((page - 1) * limit).limit(limit)],
        "total": collection.count_documents(query),
        "page": page,
        "limit": limit,
    }


@router.get("/admin/jobs")
def jobs(
    q: str = Query("", max_length=200),
    state: str = Query("", max_length=60),
    kind: str = Query("", max_length=200),
    page: int | None = Query(None, ge=1),
    limit: int = Query(10, ge=1, le=100),
    user=Depends(administrator),
    mongo=Depends(database),
):
    query = {}
    if state and state != "all":
        query["state"] = state
    if kind and kind != "all":
        query["kind"] = {"$in": kind.split(",")}
    if q.strip():
        pattern = {"$regex": re.escape(q.strip()), "$options": "i"}
        owners = [
            u["_id"]
            for u in mongo.db.users.find(
                {"$or": [{"display_name": pattern}, {"username": pattern}]}, {"_id": 1}
            )
        ]
        query["$or"] = [
            {key: pattern}
            for key in ["_id", "kind", "state", "stage", "resource_id", "error.message"]
        ] + [{"owner_id": {"$in": owners}}]
    result = paged_records(mongo.db.jobs, query, page, limit, 200)
    records = result if page is None else result["items"]
    owner_ids = [j["owner_id"] for j in records]
    users = {
        u["_id"]: u["display_name"]
        for u in mongo.db.users.find({"_id": {"$in": owner_ids}}, {"display_name": 1})
    }
    views = [
        {**job_view({**j, "_id": j["id"]}), "owner_name": users.get(j["owner_id"], j["owner_id"])}
        for j in records
    ]
    if page is None:
        return views
    return {**result, "items": views}


@router.get("/admin/jobs/{job_id}/log")
def job_log(job_id: str, user=Depends(administrator), mongo=Depends(database)):
    job = mongo.db.jobs.find_one({"_id": job_id})
    if not job:
        raise AppError("NOT_FOUND", "Không tìm thấy tác vụ.", 404)
    path = (mongo.settings.data_dir / "logs/jobs" / job_id / "worker.log").resolve()
    root = (mongo.settings.data_dir / "logs/jobs").resolve()
    if not path.is_relative_to(root):
        raise AppError("INVALID_PATH", "Đường dẫn không hợp lệ.", 422)
    mongo.audit(user["_id"], "job_log_viewed", job_id)
    return {
        "text": path.read_text(errors="replace")[-100000:]
        if path.is_file()
        else "Chưa có log worker."
    }


@router.post("/admin/jobs/{job_id}/{action}")
def operate_job(job_id: str, action: str, user=Depends(administrator), mongo=Depends(database)):
    from meeting_backend.modules.jobs.service import cancel, retry

    if action not in {"cancel", "retry"}:
        raise AppError("NOT_FOUND", "Thao tác không tồn tại.", 404)
    job = mongo.db.jobs.find_one({"_id": job_id})
    if not job:
        raise AppError("NOT_FOUND", "Không tìm thấy tác vụ.", 404)
    owner = mongo.db.users.find_one({"_id": job["owner_id"]})
    if not owner:
        raise AppError("NOT_FOUND", "Tài khoản sở hữu không tồn tại.", 404)
    result = (cancel if action == "cancel" else retry)(mongo, owner, job_id)
    mongo.audit(user["_id"], "admin_job_" + action, job_id, owner_id=job["owner_id"])
    return result


@router.get("/admin/audit")
def audit(
    q: str = Query("", max_length=200),
    page: int | None = Query(None, ge=1),
    limit: int = Query(10, ge=1, le=100),
    user=Depends(administrator),
    mongo=Depends(database),
):
    query = {}
    if q.strip():
        pattern = {"$regex": re.escape(q.strip()), "$options": "i"}
        query["$or"] = [
            {key: pattern} for key in ["action", "resource_id", "owner_id", "created_at"]
        ]
    return paged_records(mongo.db.audit_events, query, page, limit, 300)


@router.get("/admin/preset")
def get_preset(user=Depends(administrator), mongo=Depends(database)):
    return service.preset(mongo)


@router.put("/admin/preset")
def update_preset(payload: Preset, user=Depends(administrator), mongo=Depends(database)):
    before = mongo.db.settings.find_one({"_id": "processing_preset"})
    if not before:
        mongo.db.settings.update_one(
            {"_id": "processing_preset"}, {"$setOnInsert": Preset().model_dump()}, upsert=True
        )
    changes = payload.model_dump()
    changes.update(revision=payload.revision + 1, updated_by=user["_id"], updated_at=now())
    result = mongo.db.settings.find_one_and_update(
        {"_id": "processing_preset", "revision": payload.revision},
        {"$set": changes},
        return_document=ReturnDocument.AFTER,
    )
    if not result:
        raise AppError("REVISION_CONFLICT", "Cấu hình đã thay đổi. Hãy tải lại.", 409)
    mongo.audit(user["_id"], "preset_updated", "processing_preset", revision=changes["revision"])
    return service.preset(mongo)


@router.get("/admin/experiments")
def experiments(
    page: int | None = Query(None, ge=1),
    limit: int = Query(10, ge=1, le=100),
    user=Depends(administrator),
    mongo=Depends(database),
):
    return paged_records(mongo.db.experiments, {}, page, limit, 100)


@router.post("/admin/experiments", status_code=201)
def evaluate(payload: Evaluation, user=Depends(administrator), mongo=Depends(database)):
    return service.evaluate(mongo, user, payload)


def system_resource(mongo, user):
    resource_id = "system-" + user["_id"]
    mongo.db.settings.update_one(
        {"_id": resource_id},
        {
            "$setOnInsert": {
                "owner_id": user["_id"],
                "revision": 1,
                "active_job": None,
                "created_at": now(),
            }
        },
        upsert=True,
    )
    return resource_id


@router.post("/admin/backups", status_code=202)
def backup(user=Depends(administrator), mongo=Depends(database)):
    return enqueue(mongo, user, "system", system_resource(mongo, user), "backup_system")


@router.post("/admin/backups/upload", status_code=201)
def upload_backup(
    file: UploadFile = File(...), user=Depends(administrator), mongo=Depends(database)
):
    store = ArtifactStore(mongo)
    return store.view(store.upload(file, user["_id"], {".zip"}))


@router.post("/admin/restore", status_code=202)
def restore(payload: RestoreBackup, user=Depends(administrator), mongo=Depends(database)):
    artifact = mongo.db.artifacts.find_one({"_id": payload.artifact_id, "owner_id": user["_id"]})
    if not artifact:
        raise AppError("NOT_FOUND", "Không tìm thấy bản sao lưu.", 404)
    return enqueue(
        mongo,
        user,
        "system",
        system_resource(mongo, user),
        "restore_system",
        {"artifact_id": artifact["_id"]},
    )
