from fastapi import APIRouter, Depends
from pydantic import Field

from meeting_backend.api.dependencies import current_user, database
from meeting_backend.core.errors import AppError
from meeting_backend.infrastructure.mongodb.client import public
from meeting_backend.modules.meetings import timeline as timeline_service
from meeting_backend.modules.meetings.repository import MeetingRepository
from meeting_backend.modules.meetings.schemas import Revision
from meeting_backend.modules.transcripts import service

router = APIRouter(prefix="/meetings/{meeting_id}", tags=["transcripts"])


class TextEdit(Revision):
    segment_id: str
    text: str = Field(max_length=12000)


class SpeakerRename(Revision):
    speaker_key: str
    label: str = Field(min_length=1, max_length=100)


class RestoreTranscript(Revision):
    version_id: str


@router.get("/transcript")
def transcript(
    meeting_id: str,
    version_id: str | None = None,
    user=Depends(current_user),
    mongo=Depends(database),
):
    meeting = MeetingRepository(mongo).owned(meeting_id, user)
    selected = version_id or meeting.get("active_transcript_id")
    if not selected:
        return {"version": None, "segments": []}
    version = mongo.db.transcript_versions.find_one({"_id": selected, "meeting_id": meeting_id})
    if not version:
        raise AppError("NOT_FOUND", "Không tìm thấy phiên bản transcript.", 404)
    segments = []
    for row in service.rows_for(mongo, selected):
        view = service.view_row(row)
        view["context_audio"] = service.review_context(mongo, meeting, row)
        segments.append(view)
    return {
        "version": public(version),
        "segments": segments,
    }


@router.patch("/transcript")
def edit(meeting_id: str, payload: TextEdit, user=Depends(current_user), mongo=Depends(database)):
    return service.edit(mongo, user, meeting_id, payload)


@router.post("/speakers/rename")
def rename(
    meeting_id: str, payload: SpeakerRename, user=Depends(current_user), mongo=Depends(database)
):
    return service.rename(mongo, user, meeting_id, payload)


@router.post("/transcript/restore")
def restore(
    meeting_id: str, payload: RestoreTranscript, user=Depends(current_user), mongo=Depends(database)
):
    repo = MeetingRepository(mongo)
    meeting = repo.editable(meeting_id, user, payload.revision)
    prior = mongo.db.transcript_versions.find_one(
        {"_id": payload.version_id, "meeting_id": meeting_id}
    )
    if not prior:
        raise AppError("NOT_FOUND", "Không tìm thấy phiên bản.", 404)
    version = service.create_version(
        mongo,
        meeting,
        service.rows_for(mongo, prior["_id"]),
        reason="Khôi phục transcript",
        run_path=prior.get("run_path"),
        input_timeline_hash=prior.get("input_timeline_hash"),
        timing_complete=prior.get("timing_complete", True),
    )
    changes = {"active_transcript_id": version["_id"]}
    if prior.get("input_timeline_hash") is not None:
        try:
            layout = timeline_service.layout_for(
                meeting,
                timeline_service.assets_for(mongo, meeting),
            )
            current_hash = timeline_service.content_hash(layout)
        except AppError:
            current_hash = None
        if current_hash != prior["input_timeline_hash"]:
            changes.update(state="draft", transcript_stale=True)
    try:
        result = repo.update(meeting, changes, content_changed=True)
    except BaseException:
        service.discard_version(mongo, version["_id"])
        raise
    mongo.audit(user["_id"], "transcript_restored", meeting_id, version_id=version["_id"])
    return public(result)
