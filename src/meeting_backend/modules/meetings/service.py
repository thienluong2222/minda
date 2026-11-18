from meeting_backend.core.errors import AppError
from meeting_backend.infrastructure.mongodb.client import public
from meeting_backend.modules.meetings.repository import MeetingRepository


def validate_participants(mongo, user, ids):
    if len(set(ids)) != len(ids):
        raise AppError("DUPLICATE_PARTICIPANT", "Hồ sơ tham gia bị lặp.", 422)
    if mongo.db.speakers.count_documents(
        {"_id": {"$in": ids}, "owner_id": user["_id"], "trashed": False, "state": "ready"}
    ) != len(ids):
        raise AppError(
            "INVALID_PARTICIPANT", "Có hồ sơ giọng không thuộc quyền hoặc chưa sẵn sàng.", 422
        )


def create(mongo, user, payload):
    values = payload.model_dump()
    values["title"] = values["title"].strip()
    if not values["title"]:
        raise AppError("INVALID_TITLE", "Tên cuộc họp không được để trống.", 422)
    validate_participants(mongo, user, values["participant_ids"])
    result = MeetingRepository(mongo).create(
        owner_id=user["_id"],
        **values,
        state="draft",
        revision=1,
        content_revision=0,
        active_job=None,
        source_ids=[],
        active_transcript_id=None,
        active_minutes_id=None,
        minutes_stale=False,
        trashed=False,
    )
    mongo.audit(user["_id"], "meeting_created", result["_id"])
    return public(result)


def update(mongo, user, meeting_id, payload):
    repo = MeetingRepository(mongo)
    meeting = repo.editable(meeting_id, user, payload.revision)
    changes = payload.model_dump(exclude_none=True, exclude={"revision"})
    if "participant_ids" in changes:
        validate_participants(mongo, user, changes["participant_ids"])
        if changes["participant_ids"] != meeting.get("participant_ids", []):
            changes["state"] = "draft"
    if "title" in changes:
        changes["title"] = changes["title"].strip()
        if not changes["title"]:
            raise AppError("INVALID_TITLE", "Tên cuộc họp không được để trống.", 422)
    result = repo.update(meeting, changes, content_changed=True)
    mongo.audit(user["_id"], "meeting_updated", meeting_id, fields=list(changes))
    return public(result)
