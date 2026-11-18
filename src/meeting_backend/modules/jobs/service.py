"""Durable, per-resource serialized jobs. Publication is conditional on the active job."""

from pymongo import ReturnDocument

from meeting_backend.core.errors import AppError
from meeting_backend.infrastructure.mongodb.client import new_id, now, public

RESOURCE_COLLECTIONS = {
    "meeting": "meetings",
    "template": "templates",
    "speaker": "speakers",
    "system": "settings",
}


def enqueue(mongo, user, resource_type, resource_id, kind, payload=None, expected_revision=None):
    collection = mongo.db[RESOURCE_COLLECTIONS[resource_type]]
    resource = collection.find_one({"_id": resource_id, "owner_id": user["_id"]})
    if not resource or resource.get("trashed"):
        raise AppError("NOT_FOUND", "Không tìm thấy dữ liệu.", 404)
    job_id = new_id()
    revision = resource.get("revision", 1)
    if expected_revision is not None and expected_revision != revision:
        raise AppError("REVISION_CONFLICT", "Dữ liệu đã thay đổi. Hãy tải lại trước khi lưu.", 409)
    locked = collection.find_one_and_update(
        {"_id": resource_id, "revision": revision, "active_job": None},
        {"$set": {"active_job": job_id, "updated_at": now()}, "$inc": {"revision": 1}},
        return_document=ReturnDocument.AFTER,
    )
    if not locked:
        raise AppError("RESOURCE_BUSY", "Tài nguyên đang được xử lý hoặc đã thay đổi.", 409)
    from meeting_backend.modules.system.service import preset

    job = {
        "preset_snapshot": preset(mongo),
        "_id": job_id,
        "owner_id": user["_id"],
        "resource_type": resource_type,
        "resource_id": resource_id,
        "kind": kind,
        "payload": payload or {},
        "state": "queued",
        "stage": "Đang chờ xử lý",
        "created_at": now(),
        "updated_at": now(),
        "input_content_revision": resource.get("content_revision", 0),
        "cancel_requested": False,
        "attempt": 1,
    }
    try:
        if kind == "generate_minutes":
            from meeting_backend.modules.minutes.graph_settings import freeze_inputs

            job["payload"] = freeze_inputs(
                mongo, locked, user, job_id, job["payload"], job["preset_snapshot"]
            )
        mongo.db.jobs.insert_one(job)
    except BaseException:
        if kind == "generate_minutes":
            mongo.db.minutes_input_segments.delete_many({"snapshot_id": job_id})
            mongo.db.minutes_input_snapshots.delete_one({"_id": job_id})
        collection.update_one(
            {"_id": resource_id, "active_job": job_id},
            {"$set": {"active_job": None}, "$inc": {"revision": 1}},
        )
        raise
    mongo.audit(user["_id"], "job_queued", resource_id, kind=kind, job_id=job_id)
    return job_view(job)


def job_view(job):
    return {
        key: value
        for key, value in public(job).items()
        if key not in {"payload", "lease_token", "error_trace"}
    }


def owned_job(mongo, user, job_id):
    job = mongo.db.jobs.find_one({"_id": job_id, "owner_id": user["_id"]})
    if not job:
        raise AppError("NOT_FOUND", "Không tìm thấy tác vụ.", 404)
    return job


def cancel(mongo, user, job_id):
    job = owned_job(mongo, user, job_id)
    if job["state"] not in {"queued", "running"}:
        raise AppError("JOB_FINISHED", "Tác vụ đã kết thúc.", 409)
    if job["state"] == "queued":
        result = mongo.db.jobs.update_one(
            {"_id": job_id, "state": "queued"},
            {"$set": {"state": "cancelled", "completed_at": now(), "stage": "Đã hủy"}},
        )
        if result.modified_count:
            mongo.db[RESOURCE_COLLECTIONS[job["resource_type"]]].update_one(
                {"_id": job["resource_id"], "active_job": job_id},
                {"$set": {"active_job": None}, "$inc": {"revision": 1}},
            )
            return job_view(mongo.db.jobs.find_one({"_id": job_id}))
    mongo.db.jobs.update_one(
        {"_id": job_id, "state": "running"},
        {"$set": {"cancel_requested": True, "stage": "Đang chờ dừng ở điểm an toàn"}},
    )
    mongo.audit(user["_id"], "job_cancel_requested", job_id)
    return job_view(mongo.db.jobs.find_one({"_id": job_id}))


def retry(mongo, user, job_id):
    job = owned_job(mongo, user, job_id)
    if job["state"] not in {"failed", "interrupted", "cancelled"}:
        raise AppError("INVALID_RETRY", "Chỉ thử lại tác vụ lỗi, gián đoạn hoặc đã hủy.", 409)
    resource = mongo.db[RESOURCE_COLLECTIONS[job["resource_type"]]].find_one(
        {"_id": job["resource_id"]}
    )
    if not resource or resource.get("content_revision", 0) != job["input_content_revision"]:
        raise AppError("INPUT_CHANGED", "Nội dung đã thay đổi. Hãy tạo thao tác mới.", 409)
    return enqueue(
        mongo, user, job["resource_type"], job["resource_id"], job["kind"], job["payload"]
    )
