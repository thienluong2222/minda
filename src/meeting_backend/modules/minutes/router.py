from fastapi import APIRouter, Depends

from meeting_backend.api.dependencies import current_user, database
from meeting_backend.core.errors import AppError
from meeting_backend.infrastructure.mongodb.client import now, public
from meeting_backend.modules.jobs.service import enqueue
from meeting_backend.modules.meetings.repository import MeetingRepository
from meeting_backend.modules.meetings.schemas import Revision
from meeting_backend.modules.minutes.schemas import (
    EditFacts,
    GenerateMinutes,
    Reformat,
    RestoreMinutes,
)

router = APIRouter(prefix="/meetings/{meeting_id}/minutes", tags=["minutes"])


def current(mongo, user, meeting_id, version_id=None):
    meeting = MeetingRepository(mongo).owned(meeting_id, user)
    selected = version_id or meeting.get("active_minutes_id")
    if not selected:
        return meeting, None
    version = mongo.db.minutes_versions.find_one({"_id": selected, "meeting_id": meeting_id})
    if not version:
        raise AppError("NOT_FOUND", "Không tìm thấy phiên bản biên bản.", 404)
    return meeting, version


@router.get("")
def get_minutes(
    meeting_id: str,
    version_id: str | None = None,
    user=Depends(current_user),
    mongo=Depends(database),
):
    meeting, version = current(mongo, user, meeting_id, version_id)
    return {
        "version": public(version),
        "stale": bool(
            version and version.get("input_content_revision") != meeting.get("content_revision")
        ),
        "meeting_revision": meeting["revision"],
    }


@router.post("/generate", status_code=202)
def generate(
    meeting_id: str, payload: GenerateMinutes, user=Depends(current_user), mongo=Depends(database)
):
    meeting = MeetingRepository(mongo).owned(meeting_id, user)
    if not meeting.get("active_transcript_id"):
        raise AppError("NO_TRANSCRIPT", "Hãy xử lý âm thanh trước khi tạo biên bản.", 422)
    if meeting.get("state") == "draft":
        raise AppError(
            "AUDIO_INPUT_CHANGED",
            "Nguồn ghi âm hoặc hồ sơ người tham gia đã thay đổi. "
            "Hãy xử lý lại âm thanh trước khi tạo biên bản mới.",
            409,
        )
    template = mongo.db.templates.find_one(
        {"_id": payload.template_id, "trashed": False, "state": "ready"}
    )
    if not template or (
        template["owner_id"] != user["_id"] and template.get("visibility") != "shared"
    ):
        raise AppError(
            "INVALID_TEMPLATE",
            "Mẫu không tồn tại, chưa duyệt hoặc không thuộc quyền truy cập.",
            422,
        )
    if template.get("needs_review"):
        raise AppError(
            "TEMPLATE_REVIEW_REQUIRED", "Hãy kiểm tra và duyệt mẫu OCR trước khi sử dụng.", 422
        )
    if payload.options.mode == "general" and not payload.options.use_model:
        raise AppError("MODEL_REQUIRED", "Biên bản tổng quát cần bật LLM.", 422)
    if payload.options.two_sided and payload.options.format_standard != "hd05_2026":
        raise AppError("INVALID_FORMAT", "In hai mặt hiện áp dụng cho thể thức Đảng.", 422)
    return enqueue(
        mongo,
        user,
        "meeting",
        meeting_id,
        "generate_minutes",
        {
            "template_id": template["_id"],
            "template_version_id": template["active_version_id"],
            "options": payload.options.model_dump(),
        },
        payload.revision,
    )


@router.patch("/facts", status_code=202)
def edit_facts(
    meeting_id: str, payload: EditFacts, user=Depends(current_user), mongo=Depends(database)
):
    _meeting, version = current(mongo, user, meeting_id)
    if not version:
        raise AppError("NO_MINUTES", "Hãy tạo biên bản trước.", 422)
    if not payload.patches:
        return {"state": "unchanged"}
    known = {f["field_id"] for f in version["facts"]}
    ids = [p.field_id for p in payload.patches]
    if len(set(ids)) != len(ids) or not set(ids) <= known:
        raise AppError("INVALID_FIELDS", "Có trường không tồn tại hoặc bị lặp.", 422)
    return enqueue(
        mongo,
        user,
        "meeting",
        meeting_id,
        "edit_facts",
        {"patches": [p.model_dump(exclude_unset=True) for p in payload.patches]},
        payload.revision,
    )


@router.post("/format", status_code=202)
def reformat(
    meeting_id: str, payload: Reformat, user=Depends(current_user), mongo=Depends(database)
):
    _, version = current(mongo, user, meeting_id)
    if not version:
        raise AppError("NO_MINUTES", "Hãy tạo biên bản trước.", 422)
    return enqueue(
        mongo,
        user,
        "meeting",
        meeting_id,
        "format_minutes",
        {"options": payload.options.model_dump()},
        payload.revision,
    )


@router.post("/review")
def reviewed(
    meeting_id: str, payload: Revision, user=Depends(current_user), mongo=Depends(database)
):
    repo = MeetingRepository(mongo)
    meeting = repo.editable(meeting_id, user, payload.revision)
    if not meeting.get("active_minutes_id") or meeting.get("minutes_stale"):
        raise AppError(
            "STALE_DOCUMENT", "Hãy cập nhật biên bản theo nội dung mới trước khi xác nhận.", 409
        )
    updated = repo.update(
        meeting, {"reviewed_at": now(), "reviewed_version": meeting["active_minutes_id"]}
    )
    mongo.audit(
        user["_id"], "minutes_reviewed", meeting_id, version_id=meeting["active_minutes_id"]
    )
    return public(updated)


@router.post("/restore", status_code=202)
def restore(
    meeting_id: str, payload: RestoreMinutes, user=Depends(current_user), mongo=Depends(database)
):
    _, version = current(mongo, user, meeting_id, payload.version_id)
    return enqueue(
        mongo,
        user,
        "meeting",
        meeting_id,
        "restore_minutes",
        {"version_id": version["_id"]},
        payload.revision,
    )
