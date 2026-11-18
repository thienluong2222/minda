import re

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import Field

from meeting_backend.api.dependencies import current_user, database
from meeting_backend.core.errors import AppError
from meeting_backend.infrastructure.artifacts.store import DOCUMENT_EXTENSIONS, ArtifactStore
from meeting_backend.infrastructure.mongodb.client import new_id, now, public
from meeting_backend.modules.jobs.service import enqueue
from meeting_backend.modules.meetings.schemas import Revision

router = APIRouter(prefix="/templates", tags=["templates"])


class TemplateReview(Revision):
    fields: list[dict] = Field(default_factory=list, max_length=500)
    paragraphs: list[dict] = Field(default_factory=list, max_length=2000)
    approved: bool = False


@router.get("")
def list_templates(
    q: str = Query("", max_length=200),
    visibility: str = "all",
    state: str = "all",
    page: int | None = Query(None, ge=1),
    limit: int = Query(10, ge=1, le=100),
    user=Depends(current_user),
    mongo=Depends(database),
):
    query = {"trashed": False, "$or": [{"owner_id": user["_id"]}, {"visibility": "shared"}]}
    if q.strip():
        query["name"] = {"$regex": re.escape(q.strip()), "$options": "i"}
    if visibility in {"private", "shared"}:
        query["visibility"] = visibility
    if state == "needs_review":
        query["needs_review"] = True
    elif state == "ready":
        query.update(state="ready", needs_review=False, active_job=None)
    elif state == "processing":
        query["$and"] = [{"$or": [{"active_job": {"$ne": None}}, {"state": "pending"}]}]
    cursor = mongo.db.templates.find(query).sort([("created_at", -1), ("_id", 1)])
    if page is None:
        return [public(t) for t in cursor]
    return {
        "items": [public(t) for t in cursor.skip((page - 1) * limit).limit(limit)],
        "total": mongo.db.templates.count_documents(query),
        "page": page,
        "limit": limit,
    }


@router.post("", status_code=202)
def upload_template(
    name: str = Form(..., min_length=1, max_length=200),
    visibility: str = Form("private"),
    file: UploadFile = File(...),
    user=Depends(current_user),
    mongo=Depends(database),
):
    if visibility not in {"private", "shared"} or (
        visibility == "shared" and user["role"] != "admin"
    ):
        raise AppError("INVALID_VISIBILITY", "Chỉ admin được phát hành mẫu dùng chung.", 403)
    template_id = new_id()
    artifact = ArtifactStore(mongo).upload(
        file, user["_id"], DOCUMENT_EXTENSIONS, resource_id=template_id, visibility=visibility
    )
    mongo.db.templates.insert_one(
        {
            "_id": template_id,
            "owner_id": user["_id"],
            "name": name.strip(),
            "visibility": visibility,
            "state": "pending",
            "active_job": None,
            "revision": 1,
            "input_artifact_id": artifact["_id"],
            "active_version_id": None,
            "needs_review": True,
            "trashed": False,
            "created_at": now(),
            "updated_at": now(),
        }
    )
    job = enqueue(mongo, user, "template", template_id, "ingest_template")
    return {"template_id": template_id, "job": job}


@router.get("/{template_id}")
def get_template(template_id: str, user=Depends(current_user), mongo=Depends(database)):
    template = mongo.db.templates.find_one(
        {
            "_id": template_id,
            "trashed": False,
            "$or": [{"owner_id": user["_id"]}, {"visibility": "shared"}],
        }
    )
    if not template:
        raise AppError("NOT_FOUND", "Không tìm thấy mẫu.", 404)
    version = mongo.db.template_versions.find_one({"_id": template.get("active_version_id")})
    return {**public(template), "version": public(version)}


@router.post("/{template_id}/review", status_code=202)
def review_template(
    template_id: str, payload: TemplateReview, user=Depends(current_user), mongo=Depends(database)
):
    template = mongo.db.templates.find_one(
        {"_id": template_id, "owner_id": user["_id"], "state": "ready", "trashed": False}
    )
    if not template:
        raise AppError("NOT_FOUND", "Mẫu không thuộc quyền sửa hoặc chưa sẵn sàng.", 404)
    return enqueue(
        mongo,
        user,
        "template",
        template_id,
        "review_template",
        payload.model_dump(exclude={"revision"}),
        payload.revision,
    )


@router.post("/{template_id}/archive")
def archive(
    template_id: str, payload: Revision, user=Depends(current_user), mongo=Depends(database)
):
    result = mongo.db.templates.update_one(
        {
            "_id": template_id,
            "owner_id": user["_id"],
            "revision": payload.revision,
            "active_job": None,
        },
        {"$set": {"trashed": True, "updated_at": now()}, "$inc": {"revision": 1}},
    )
    if not result.matched_count:
        raise AppError("REVISION_CONFLICT", "Mẫu đã thay đổi hoặc đang được xử lý.", 409)
    mongo.audit(user["_id"], "template_archived", template_id)
    return {"status": "ok"}
