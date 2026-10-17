import re

from fastapi import APIRouter, Depends, File, Query, UploadFile

from meeting_backend.api.dependencies import current_user, database
from meeting_backend.core.errors import AppError
from meeting_backend.infrastructure.artifacts.media import probe_audio
from meeting_backend.infrastructure.artifacts.store import AUDIO_EXTENSIONS, ArtifactStore
from meeting_backend.infrastructure.mongodb.client import now, public
from meeting_backend.modules.jobs.service import enqueue
from meeting_backend.modules.meetings import service
from meeting_backend.modules.meetings.repository import MeetingRepository
from meeting_backend.modules.meetings.schemas import MeetingCreate, MeetingUpdate, Revision

router = APIRouter(prefix="/meetings", tags=["meetings"])


@router.get("")
def list_meetings(
    q: str = "",
    trashed: bool = False,
    page: int = Query(1, ge=1),
    limit: int = Query(30, ge=1, le=100),
    user=Depends(current_user),
    mongo=Depends(database),
):
    query = {"owner_id": user["_id"], "trashed": trashed}
    if q:
        query["title"] = {"$regex": re.escape(q[:200]), "$options": "i"}
    return {
        "items": [
            public(m)
            for m in mongo.db.meetings.find(query)
            .sort("updated_at", -1)
            .skip((page - 1) * limit)
            .limit(limit)
        ],
        "total": mongo.db.meetings.count_documents(query),
        "page": page,
        "limit": limit,
    }


@router.post("", status_code=201)
def create(payload: MeetingCreate, user=Depends(current_user), mongo=Depends(database)):
    return service.create(mongo, user, payload)


@router.get("/{meeting_id}")
def get(meeting_id: str, user=Depends(current_user), mongo=Depends(database)):
    meeting = MeetingRepository(mongo).owned(meeting_id, user)
    sources = list(
        mongo.db.sources.find(
            {"_id": {"$in": meeting.get("source_ids", [])}, "owner_id": user["_id"]}
        )
    )
    store = ArtifactStore(mongo)
    for source in sources:
        artifact = mongo.db.artifacts.find_one({"_id": source["artifact_id"]})
        source["artifact"] = store.view(artifact) if artifact else None
    return {**public(meeting), "sources": [public(s) for s in sources]}


@router.patch("/{meeting_id}")
def update(
    meeting_id: str, payload: MeetingUpdate, user=Depends(current_user), mongo=Depends(database)
):
    return service.update(mongo, user, meeting_id, payload)


@router.post("/{meeting_id}/sources", status_code=201)
def upload_sources(
    meeting_id: str,
    files: list[UploadFile] = File(...),
    revision: int = Query(...),
    user=Depends(current_user),
    mongo=Depends(database),
):
    repo = MeetingRepository(mongo)
    meeting = repo.editable(meeting_id, user, revision)
    count = len(meeting.get("source_ids", []))
    if not files or count + len(files) > mongo.settings.max_sources:
        raise AppError("SOURCE_LIMIT", "Mỗi cuộc họp hỗ trợ từ 1 đến 8 nguồn âm thanh.", 422)
    store = ArtifactStore(mongo)
    created = []
    uploaded = []
    try:
        for upload in files:
            artifact = store.upload(upload, user["_id"], AUDIO_EXTENSIONS, resource_id=meeting_id)
            uploaded.append(artifact)
            metadata = probe_audio(store.resolve(artifact))
            source = {
                "_id": artifact["_id"],
                "owner_id": user["_id"],
                "meeting_id": meeting_id,
                "artifact_id": artifact["_id"],
                "name": artifact["name"],
                "created_at": now(),
                **metadata,
            }
            mongo.db.sources.insert_one(source)
            created.append(source)
        result = repo.update(
            meeting,
            {
                "state": "draft",
                "source_ids": meeting.get("source_ids", []) + [s["_id"] for s in created],
            },
            content_changed=True,
        )
    except BaseException:
        for source in created:
            mongo.db.sources.delete_one({"_id": source["_id"]})
        for artifact in uploaded:
            store.resolve(artifact).unlink(missing_ok=True)
            mongo.db.artifacts.delete_one({"_id": artifact["_id"], "owner_id": user["_id"]})
        raise
    mongo.audit(user["_id"], "sources_uploaded", meeting_id, count=len(created))
    return public(result)


@router.delete("/{meeting_id}/sources/{source_id}")
def remove_source(
    meeting_id: str,
    source_id: str,
    payload: Revision,
    user=Depends(current_user),
    mongo=Depends(database),
):
    repo = MeetingRepository(mongo)
    meeting = repo.editable(meeting_id, user, payload.revision)
    source = mongo.db.sources.find_one({"_id": source_id, "meeting_id": meeting_id})
    if not source:
        raise AppError("NOT_FOUND", "Không tìm thấy nguồn.", 404)
    result = repo.update(
        meeting,
        {
            "state": "draft",
            "source_ids": [s for s in meeting.get("source_ids", []) if s != source_id],
        },
        content_changed=True,
    )
    mongo.audit(user["_id"], "source_removed", meeting_id, source_id=source_id)
    return public(result)


@router.post("/{meeting_id}/process", status_code=202)
def process(
    meeting_id: str, payload: Revision, user=Depends(current_user), mongo=Depends(database)
):
    meeting = MeetingRepository(mongo).editable(meeting_id, user, payload.revision)
    if not meeting.get("source_ids"):
        raise AppError("NO_SOURCES", "Hãy tải âm thanh trước khi xử lý.", 422)
    return enqueue(
        mongo, user, "meeting", meeting_id, "transcribe", expected_revision=payload.revision
    )


@router.post("/{meeting_id}/trash")
def trash(meeting_id: str, payload: Revision, user=Depends(current_user), mongo=Depends(database)):
    repo = MeetingRepository(mongo)
    meeting = repo.editable(meeting_id, user, payload.revision)
    result = repo.update(meeting, {"trashed": True})
    mongo.audit(user["_id"], "meeting_trashed", meeting_id)
    return public(result)


@router.post("/{meeting_id}/restore")
def restore(
    meeting_id: str, payload: Revision, user=Depends(current_user), mongo=Depends(database)
):
    repo = MeetingRepository(mongo)
    meeting = repo.owned(meeting_id, user)
    if meeting["revision"] != payload.revision or meeting.get("active_job"):
        raise AppError("REVISION_CONFLICT", "Dữ liệu đã thay đổi hoặc đang xử lý.", 409)
    result = repo.update(meeting, {"trashed": False})
    mongo.audit(user["_id"], "meeting_restored", meeting_id)
    return public(result)


@router.get("/{meeting_id}/history")
def history(meeting_id: str, user=Depends(current_user), mongo=Depends(database)):
    MeetingRepository(mongo).owned(meeting_id, user)
    return {
        "transcripts": [
            public(v)
            for v in mongo.db.transcript_versions.find({"meeting_id": meeting_id}).sort(
                "created_at", -1
            )
        ],
        "minutes": [
            public(v)
            for v in mongo.db.minutes_versions.find(
                {"meeting_id": meeting_id}, {"facts": 0, "schema": 0, "topics": 0, "corrections": 0}
            ).sort("created_at", -1)
        ],
        "events": [
            public(e)
            for e in mongo.db.audit_events.find(
                {"owner_id": user["_id"], "resource_id": meeting_id}
            )
            .sort("created_at", -1)
            .limit(100)
        ],
    }
