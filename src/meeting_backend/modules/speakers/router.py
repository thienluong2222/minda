import re

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile

from meeting_backend.api.dependencies import current_user, database
from meeting_backend.core.errors import AppError
from meeting_backend.infrastructure.artifacts.store import AUDIO_EXTENSIONS, ArtifactStore
from meeting_backend.infrastructure.mongodb.client import new_id, now, public
from meeting_backend.modules.jobs.service import enqueue
from meeting_backend.modules.meetings.schemas import Revision

router = APIRouter(prefix="/speakers", tags=["speakers"])


@router.get("")
def list_speakers(
    q: str = Query("", max_length=200),
    page: int | None = Query(None, ge=1),
    limit: int = Query(10, ge=1, le=100),
    user=Depends(current_user),
    mongo=Depends(database),
):
    store = ArtifactStore(mongo)
    result = []
    query = {"owner_id": user["_id"], "trashed": False}
    if q.strip():
        query["name"] = {"$regex": re.escape(q.strip()), "$options": "i"}
    cursor = mongo.db.speakers.find(query).sort([("created_at", -1), ("_id", 1)])
    if page is not None:
        cursor = cursor.skip((page - 1) * limit).limit(limit)
    for profile in cursor:
        samples = []
        for artifact_id in profile.get("sample_ids", []):
            artifact = mongo.db.artifacts.find_one({"_id": artifact_id})
            if artifact:
                samples.append(store.view(artifact))
        result.append({**public(profile), "samples": samples})
    return (
        result
        if page is None
        else {
            "items": result,
            "total": mongo.db.speakers.count_documents(query),
            "page": page,
            "limit": limit,
        }
    )


@router.get("/{speaker_id}")
def get_speaker(speaker_id: str, user=Depends(current_user), mongo=Depends(database)):
    profile = mongo.db.speakers.find_one(
        {"_id": speaker_id, "owner_id": user["_id"], "trashed": False}
    )
    if not profile:
        raise AppError("NOT_FOUND", "Không tìm thấy hồ sơ giọng.", 404)
    store = ArtifactStore(mongo)
    samples = []
    for artifact_id in profile.get("sample_ids", []):
        artifact = mongo.db.artifacts.find_one({"_id": artifact_id})
        if artifact:
            samples.append(store.view(artifact))
    meetings = [
        {
            "id": m["_id"],
            "title": m.get("title", ""),
            "date": m.get("date", ""),
            "state": m.get("state", "draft"),
            "updated_at": m.get("updated_at") or m.get("created_at", ""),
        }
        for m in mongo.db.meetings.find(
            {"owner_id": user["_id"], "trashed": False, "participant_ids": speaker_id},
            {"_id": 1, "title": 1, "date": 1, "state": 1, "updated_at": 1, "created_at": 1},
        ).sort("updated_at", -1)
    ]
    return {**public(profile), "samples": samples, "meetings": meetings}


@router.post("", status_code=202)
def create_speaker(
    name: str = Form(..., min_length=1, max_length=200),
    samples: list[UploadFile] = File(...),
    user=Depends(current_user),
    mongo=Depends(database),
):
    if not 1 <= len(samples) <= 8:
        raise AppError("SAMPLE_LIMIT", "Cần từ 1 đến 8 mẫu giọng.", 422)
    speaker_id = new_id()
    store = ArtifactStore(mongo)
    artifacts = [
        store.upload(f, user["_id"], AUDIO_EXTENSIONS, resource_id=speaker_id) for f in samples
    ]
    record = {
        "_id": speaker_id,
        "owner_id": user["_id"],
        "name": name.strip(),
        "state": "pending",
        "sample_ids": [a["_id"] for a in artifacts],
        "active_job": None,
        "revision": 1,
        "created_at": now(),
        "updated_at": now(),
        "trashed": False,
    }
    mongo.db.speakers.insert_one(record)
    return {
        "speaker_id": speaker_id,
        "job": enqueue(mongo, user, "speaker", speaker_id, "enroll_voice"),
    }


@router.post("/{speaker_id}/samples", status_code=202)
def add_samples(
    speaker_id: str,
    revision: int = Form(...),
    samples: list[UploadFile] = File(...),
    user=Depends(current_user),
    mongo=Depends(database),
):
    profile = mongo.db.speakers.find_one(
        {"_id": speaker_id, "owner_id": user["_id"], "trashed": False}
    )
    if not profile:
        raise AppError("NOT_FOUND", "Không tìm thấy hồ sơ giọng.", 404)
    if not 1 <= len(samples) or len(samples) + len(profile.get("sample_ids", [])) > 8:
        raise AppError("SAMPLE_LIMIT", "Tối đa 8 mẫu cho một hồ sơ.", 422)
    store = ArtifactStore(mongo)
    artifacts = [
        store.upload(f, user["_id"], AUDIO_EXTENSIONS, resource_id=speaker_id) for f in samples
    ]
    return enqueue(
        mongo,
        user,
        "speaker",
        speaker_id,
        "enroll_voice",
        {"sample_ids": profile.get("sample_ids", []) + [a["_id"] for a in artifacts]},
        revision,
    )


@router.post("/{speaker_id}/archive")
def archive(
    speaker_id: str, payload: Revision, user=Depends(current_user), mongo=Depends(database)
):
    if mongo.db.meetings.count_documents(
        {"owner_id": user["_id"], "trashed": False, "participant_ids": speaker_id}
    ):
        raise AppError(
            "PROFILE_IN_USE", "Hãy bỏ chọn hồ sơ khỏi các cuộc họp trước khi lưu trữ.", 409
        )
    result = mongo.db.speakers.update_one(
        {
            "_id": speaker_id,
            "owner_id": user["_id"],
            "revision": payload.revision,
            "active_job": None,
        },
        {"$set": {"trashed": True, "updated_at": now()}, "$inc": {"revision": 1}},
    )
    if not result.matched_count:
        raise AppError("REVISION_CONFLICT", "Hồ sơ đã thay đổi hoặc đang xử lý.", 409)
    mongo.audit(user["_id"], "speaker_archived", speaker_id)
    return {"status": "ok"}
