import re
from typing import Literal

from fastapi import APIRouter, Depends, Query

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
    ReviseOutline,
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
    transcript = mongo.db.transcript_versions.find_one({"_id": meeting["active_transcript_id"]})
    if transcript and transcript.get("timing_complete") is False:
        raise AppError(
            "TIMELINE_REVIEW_REQUIRED",
            "Còn phần chưa căn được vào đồng hồ chung hoặc mốc đang mâu thuẫn. "
            "Hãy rà timeline và xử lý lại trước khi tạo biên bản.",
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
    from meeting_backend.modules.system.service import preset

    if (
        payload.options.mode == "general"
        and not payload.options.use_model
        and not preset(mongo).get("minutes_graph_enabled", True)
    ):
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
            "agenda": payload.agenda,
            "turn_sessions": payload.turn_sessions,
        },
        payload.revision,
    )


def graph_scope(mongo, user, meeting_id, version_id=None):
    _, version = current(mongo, user, meeting_id, version_id)
    if not version or not version.get("graph_id"):
        raise AppError("NO_MEETING_GRAPH", "Phiên bản biên bản này chưa có đồ thị.", 404)
    return {"owner_id": user["_id"], "meeting_id": meeting_id, "graph_id": version["graph_id"]}


@router.get("/graph")
def get_graph(
    meeting_id: str,
    version_id: str | None = None,
    user=Depends(current_user),
    mongo=Depends(database),
):
    return public(
        mongo.db.meeting_graph_versions.find_one(graph_scope(mongo, user, meeting_id, version_id))
    )


@router.get("/outline")
def get_outline(
    meeting_id: str,
    version_id: str | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(12, ge=1, le=20),
    user=Depends(current_user),
    mongo=Depends(database),
):
    from meeting_backend.modules.minutes.outline_store import outline_page

    _, version = current(mongo, user, meeting_id, version_id)
    if not version or not version.get("outline"):
        return {"available": False, "items": [], "total": 0, "page": page, "limit": limit}
    scope = {"owner_id": user["_id"], "meeting_id": meeting_id, "version_id": version["_id"]}
    return {
        "available": True,
        "metadata": version["outline"],
        **outline_page(mongo, scope, page, limit),
    }


@router.get("/outline/items")
def get_outline_items(
    meeting_id: str,
    section_id: str = Query(..., max_length=200),
    version_id: str | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
    user=Depends(current_user),
    mongo=Depends(database),
):
    _, version = current(mongo, user, meeting_id, version_id)
    if not version or not version.get("outline"):
        raise AppError("NO_MEETING_OUTLINE", "Phiên bản này chưa lưu dàn ý.", 404)
    scope = {
        "owner_id": user["_id"],
        "meeting_id": meeting_id,
        "version_id": version["_id"],
        "section_id": section_id,
    }
    return graph_page(mongo.db.meeting_outline_items, scope, page, limit, "")


@router.get("/outline/draft")
def outline_draft(meeting_id: str, user=Depends(current_user), mongo=Depends(database)):
    from meeting_backend.modules.minutes.outline_store import load_editable_plan

    meeting, version = current(mongo, user, meeting_id)
    _, plan = load_editable_plan(mongo, meeting, version)
    return {
        "plan_id": plan.plan_id,
        "version_id": version["_id"],
        "revision": meeting["revision"],
        "sections": [
            {
                "section_id": section.section_id,
                "title": section.title,
                "items": [
                    item.model_dump(include={"item_id", "role", "text", "priority", "included"})
                    for item in section.outline
                ],
            }
            for section in plan.sections
        ],
    }


@router.patch("/outline", status_code=202)
def edit_outline(
    meeting_id: str, payload: ReviseOutline, user=Depends(current_user), mongo=Depends(database)
):
    from meeting_backend.modules.minutes.outline_store import load_editable_plan
    from meeting_pipeline.minutes.graph_contracts import MeetingGraph
    from meeting_pipeline.minutes.graph_plan import revise_plan

    meeting, version = current(mongo, user, meeting_id)
    if not version or version["_id"] != payload.version_id:
        raise AppError("OUTLINE_STALE", "Phiên bản biên bản đã thay đổi. Hãy tải lại.", 409)
    run, plan = load_editable_plan(mongo, meeting, version)
    if plan.plan_id != payload.plan_id:
        raise AppError("OUTLINE_STALE", "Dàn ý đã thay đổi. Hãy tải lại.", 409)
    graph = MeetingGraph.model_validate_json((run / "minutes/meeting_graph.json").read_text())
    try:
        revised, changed = revise_plan(plan, graph, payload.sections)
    except ValueError as exc:
        raise AppError("INVALID_OUTLINE", str(exc), 422) from exc
    has_edits = bool(changed) or [
        (s.section_id, s.title) for s in revised.sections
    ] != [(s.section_id, s.title) for s in plan.sections]
    if not has_edits:
        return {"state": "unchanged"}
    return enqueue(
        mongo,
        user,
        "meeting",
        meeting_id,
        "revise_minutes_outline",
        payload.model_dump(exclude={"revision"}),
        payload.revision,
    )


def graph_page(collection, scope, page, limit, kind, node_id=None):
    query = dict(scope)
    if kind:
        query["value.kind"] = kind
    if node_id:
        query["$or"] = [{"value.source": node_id}, {"value.target": node_id}]
    return {
        "items": [
            row["value"]
            for row in collection.find(query).sort("index", 1).skip((page - 1) * limit).limit(limit)
        ],
        "total": collection.count_documents(query),
        "page": page,
        "limit": limit,
    }


@router.get("/graph/nodes")
def graph_nodes(
    meeting_id: str,
    version_id: str | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    kind: str = Query("", max_length=80),
    q: str = Query("", max_length=200),
    user=Depends(current_user),
    mongo=Depends(database),
):
    scope = graph_scope(mongo, user, meeting_id, version_id)
    if q.strip():
        scope["value.label"] = {"$regex": re.escape(q.strip()), "$options": "i"}
    return graph_page(
        mongo.db.meeting_graph_nodes,
        scope,
        page,
        limit,
        kind,
    )


@router.get("/graph/view")
def get_graph_view(
    meeting_id: str,
    version_id: str | None = None,
    node_id: str = Query("", max_length=200),
    page: int = Query(1, ge=1),
    limit: int = Query(40, ge=1, le=100),
    mode: Literal["content", "technical"] = "technical",
    user=Depends(current_user),
    mongo=Depends(database),
):
    from meeting_backend.modules.minutes.graph_view import graph_view

    if mode == "content":
        from meeting_backend.modules.minutes.graph_content_view import content_view

        return content_view(
            mongo, graph_scope(mongo, user, meeting_id, version_id), node_id, page, limit
        )
    return graph_view(mongo, graph_scope(mongo, user, meeting_id, version_id), node_id, page, limit)


@router.get("/graph/edges")
def graph_edges(
    meeting_id: str,
    version_id: str | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    kind: str = Query("", max_length=80),
    node_id: str = Query("", max_length=200),
    user=Depends(current_user),
    mongo=Depends(database),
):
    return graph_page(
        mongo.db.meeting_graph_edges,
        graph_scope(mongo, user, meeting_id, version_id),
        page,
        limit,
        kind,
        node_id,
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
    options = payload.options.model_dump()
    options["graph_enabled"] = bool(version.get("options", {}).get("graph_enabled", False))
    return enqueue(
        mongo,
        user,
        "meeting",
        meeting_id,
        "format_minutes",
        {"options": options},
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
    pending = mongo.db.minutes_versions.find_one(
        {
            "_id": meeting["active_minutes_id"],
            "facts": {
                "$elemMatch": {"$or": [{"previous_edit": {"$ne": None}}, {"status": "conflicting"}]}
            },
        },
        {"_id": 1},
    )
    if pending:
        raise AppError(
            "FACT_REVIEW_REQUIRED",
            "Hãy xử lý các dữ kiện mâu thuẫn trước khi xác nhận biên bản.",
            409,
        )
    updated = repo.update(
        meeting, {"reviewed_at": now(), "reviewed_version": meeting["active_minutes_id"]}
    )
    mongo.audit(
        user["_id"], "minutes_reviewed", meeting_id, version_id=meeting["active_minutes_id"]
    )
    from meeting_backend.modules.minutes.graph_settings import learn_reviewed_style

    learn_reviewed_style(mongo, user, meeting_id, meeting["active_minutes_id"])
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
