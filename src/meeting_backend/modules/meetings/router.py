import re
from typing import Literal

from fastapi import APIRouter, Depends, File, Query, UploadFile

from meeting_backend.api.dependencies import current_user, database
from meeting_backend.core.errors import AppError
from meeting_backend.infrastructure.artifacts.media import probe_audio
from meeting_backend.infrastructure.artifacts.store import AUDIO_EXTENSIONS, ArtifactStore
from meeting_backend.infrastructure.mongodb.client import now, public
from meeting_backend.modules.jobs.service import enqueue
from meeting_backend.modules.meetings import service
from meeting_backend.modules.meetings import timeline as timeline_service
from meeting_backend.modules.meetings.repository import MeetingRepository
from meeting_backend.modules.meetings.schemas import MeetingCreate, MeetingUpdate, Revision
from meeting_backend.modules.meetings.timeline_schemas import TimelinePatch
from meeting_pipeline.config import load_config

router = APIRouter(prefix="/meetings", tags=["meetings"])


@router.get("")
def list_meetings(
    q: str = "",
    status: Literal[
        "", "draft", "processing", "transcript_ready", "minutes_ready", "needs_review"
    ] = "",
    trashed: bool = False,
    page: int = Query(1, ge=1),
    limit: int = Query(30, ge=1, le=100),
    user=Depends(current_user),
    mongo=Depends(database),
):
    query = {"owner_id": user["_id"], "trashed": trashed}
    if status == "processing":
        query["active_job"] = {"$ne": None}
    elif status == "needs_review":
        query["active_minutes_id"] = {"$ne": None}
        query["$or"] = [
            {"minutes_stale": True},
            {"$expr": {"$ne": [{"$ifNull": ["$reviewed_version", None]}, "$active_minutes_id"]}},
        ]
    elif status:
        query.update(state=status, active_job=None)
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


@router.get("/{meeting_id}/timeline")
def get_timeline(meeting_id: str, user=Depends(current_user), mongo=Depends(database)):
    meeting = MeetingRepository(mongo).owned(meeting_id, user)
    return timeline_service.view(mongo, meeting)


@router.patch("/{meeting_id}/timeline")
def patch_timeline(
    meeting_id: str, payload: TimelinePatch, user=Depends(current_user), mongo=Depends(database)
):
    return timeline_service.patch(mongo, user, meeting_id, payload)


@router.post("/{meeting_id}/sources", status_code=201)
def upload_sources(
    meeting_id: str,
    files: list[UploadFile] = File(...),
    revision: int = Query(...),
    track_id: str | None = Query(None),
    timeline_mode: bool = Query(False),
    user=Depends(current_user),
    mongo=Depends(database),
):
    repo = MeetingRepository(mongo)
    meeting = repo.editable(meeting_id, user, revision)
    count = len(meeting.get("source_ids", []))
    uses_timeline = meeting.get("timeline") is not None or timeline_mode or track_id is not None
    file_limit = mongo.settings.max_source_files if uses_timeline else mongo.settings.max_sources
    if not files or count + len(files) > file_limit:
        raise AppError(
            "SOURCE_LIMIT", f"Số file vượt giới hạn {file_limit} của chế độ hiện tại.", 422
        )
    assets = timeline_service.assets_for(mongo, meeting)
    if track_id is not None:
        layout = timeline_service.layout_for(meeting, assets)
        if track_id not in {track["id"] for track in layout["tracks"]}:
            raise AppError("TIMELINE_ITEM_NOT_FOUND", "Không tìm thấy hàng nguồn.", 422)
    max_duration = load_config(mongo.settings.pipeline_config).audio.max_duration_seconds
    store = ArtifactStore(mongo)
    created = []
    uploaded = []
    existing_artifacts = mongo.db.artifacts.find(
        {
            "_id": {"$in": [asset["artifact_id"] for asset in assets.values()]},
            "owner_id": user["_id"],
        }
    )
    total_bytes = sum(int(artifact.get("size_bytes") or 0) for artifact in existing_artifacts)
    byte_limit = mongo.settings.max_sources * mongo.settings.max_upload_bytes
    try:
        for upload in files:
            artifact = store.upload(upload, user["_id"], AUDIO_EXTENSIONS, resource_id=meeting_id)
            uploaded.append(artifact)
            total_bytes += artifact["size_bytes"]
            if total_bytes > byte_limit:
                raise AppError(
                    "SOURCE_STORAGE_LIMIT",
                    "Tổng dung lượng audio cuộc họp vượt giới hạn.",
                    413,
                )
            metadata = probe_audio(store.resolve(artifact), max_duration_seconds=max_duration)
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
        changes = {
            "state": "draft",
            "transcript_stale": bool(meeting.get("active_transcript_id")),
            "source_ids": meeting.get("source_ids", []) + [s["_id"] for s in created],
        }
        layout = timeline_service.append_assets(
            meeting,
            assets,
            created,
            mongo.settings,
            track_id=track_id,
            timeline_mode=timeline_mode,
        )
        if layout is not None:
            changes["timeline"] = layout
        result = repo.update(meeting, changes, content_changed=True)
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
    if meeting.get("timeline") is not None and any(
        clip["asset_id"] == source_id for clip in meeting["timeline"]["clips"]
    ):
        raise AppError(
            "TIMELINE_ASSET_IN_USE",
            "Hãy bỏ các đoạn dùng file này khỏi timeline trước.",
            409,
        )
    changes = {
        "state": "draft",
        "transcript_stale": bool(meeting.get("active_transcript_id")),
        "source_ids": [s for s in meeting.get("source_ids", []) if s != source_id],
    }
    if meeting.get("timeline") is not None:
        layout = meeting["timeline"]
        layout["unassigned_asset_ids"] = [
            item for item in layout["unassigned_asset_ids"] if item != source_id
        ]
        changes["timeline"] = layout
    result = repo.update(
        meeting,
        changes,
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
    plan = timeline_service.processing_input(
        meeting,
        timeline_service.assets_for(mongo, meeting),
        mongo.settings,
    )
    if (
        sum(bool(track["clip_ids"]) for track in plan["timeline"]["tracks"])
        > load_config(mongo.settings.pipeline_config).audio.max_sources
    ):
        raise AppError("SOURCE_LIMIT", "Số nguồn vượt giới hạn cấu hình pipeline.", 422)
    return enqueue(
        mongo,
        user,
        "meeting",
        meeting_id,
        "transcribe",
        payload={
            "source_ids": plan["source_ids"],
            "input_timeline": plan["timeline"],
            "input_timeline_hash": plan["timeline_hash"],
        },
        expected_revision=payload.revision,
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
