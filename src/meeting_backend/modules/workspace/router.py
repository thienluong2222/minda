import re
from typing import Literal

from fastapi import APIRouter, Depends, Query

from meeting_backend.api.dependencies import current_user, database
from meeting_backend.infrastructure.mongodb.client import public
from meeting_backend.modules.jobs import service as job_service

router = APIRouter(prefix="/workspace", tags=["workspace"])


def _matches_query(query_text: str, *fields: str | None) -> bool:
    if not query_text:
        return True
    needle = query_text.lower()
    return any(needle in (f or "").lower() for f in fields)


@router.get("/review")
def list_review_queue(
    q: str = Query("", max_length=200),
    kind: Literal["all", "minutes", "transcript", "templates"] = "all",
    page: int = Query(1, ge=1),
    limit: int = Query(30, ge=1, le=100),
    user=Depends(current_user),
    mongo=Depends(database),
):
    owner_id = user["_id"]
    query_text = q.strip()
    items: list[dict] = []

    if kind in {"all", "minutes", "transcript"}:
        meetings = list(
            mongo.db.meetings.find({"owner_id": owner_id, "trashed": False}).sort(
                [("updated_at", -1), ("_id", 1)]
            )
        )
        transcript_ids = [
            m["active_transcript_id"] for m in meetings if m.get("active_transcript_id")
        ]
        minutes_ids = [m["active_minutes_id"] for m in meetings if m.get("active_minutes_id")]

        transcript_review_counts: dict[str, int] = {}
        if transcript_ids and kind in {"all", "transcript"}:
            for row in mongo.db.transcript_segments.aggregate(
                [
                    {
                        "$match": {
                            "version_id": {"$in": transcript_ids},
                            "needs_review": True,
                        }
                    },
                    {"$group": {"_id": "$version_id", "count": {"$sum": 1}}},
                ]
            ):
                transcript_review_counts[row["_id"]] = int(row["count"])

        minutes_versions_by_id: dict[str, dict] = {}
        if minutes_ids and kind in {"all", "minutes"}:
            for mv in mongo.db.minutes_versions.find(
                {"_id": {"$in": minutes_ids}},
                {"_id": 1, "input_content_revision": 1, "created_at": 1},
            ):
                minutes_versions_by_id[mv["_id"]] = mv

        for m in meetings:
            reason_codes: list[str] = []
            reasons: list[str] = []
            review_count = 0

            active_minutes_id = m.get("active_minutes_id")
            active_transcript_id = m.get("active_transcript_id")

            if kind in {"all", "minutes"} and active_minutes_id:
                mv = minutes_versions_by_id.get(active_minutes_id)
                is_stale = bool(
                    m.get("minutes_stale")
                    or (mv and mv.get("input_content_revision") != m.get("content_revision"))
                )
                if is_stale:
                    reason_codes.append("minutes_stale")
                    reasons.append("Biên bản cần cập nhật theo nguồn hoặc lời chép mới")
                    review_count += 1
                elif m.get("reviewed_version") != active_minutes_id:
                    reason_codes.append("minutes_unreviewed")
                    reasons.append("Biên bản chưa được xác nhận rà soát")
                    review_count += 1

            if kind in {"all", "transcript"} and active_transcript_id:
                seg_count = transcript_review_counts.get(active_transcript_id, 0)
                if seg_count > 0:
                    reason_codes.append("transcript_needs_review")
                    reasons.append(f"{seg_count} đoạn lời chép đánh dấu cần rà soát")
                    review_count += seg_count

            if not reason_codes:
                continue

            if "minutes_stale" in reason_codes or "minutes_unreviewed" in reason_codes:
                target_tab = "minutes"
                version_id = active_minutes_id
            else:
                target_tab = "transcript"
                version_id = active_transcript_id

            target_url = f"/meetings/{m['_id']}?tab={target_tab}"
            if target_tab == "transcript":
                target_url += "&filter=review"

            subtitle_parts = [p for p in [m.get("date"), m.get("location")] if p]
            subtitle = " · ".join(subtitle_parts) if subtitle_parts else "Cuộc họp"

            if not _matches_query(
                query_text,
                m.get("title"),
                subtitle,
                " ".join(reasons),
                " ".join(reason_codes),
            ):
                continue

            items.append(
                {
                    "id": f"meeting:{m['_id']}",
                    "resource_type": "meeting",
                    "resource_id": m["_id"],
                    "title": m.get("title", ""),
                    "subtitle": subtitle,
                    "state": m.get("state", "draft"),
                    "target_url": target_url,
                    "target_tab": target_tab,
                    "reason_codes": reason_codes,
                    "reasons": reasons,
                    "review_count": review_count,
                    "version_id": version_id,
                    "updated_at": m.get("updated_at") or m.get("created_at", ""),
                }
            )

    if kind in {"all", "templates"}:
        templates = list(
            mongo.db.templates.find(
                {"owner_id": owner_id, "trashed": False, "needs_review": True}
            ).sort([("updated_at", -1), ("_id", 1)])
        )
        for t in templates:
            reason_codes = ["template_needs_review"]
            reasons = ["Mẫu biên bản cần kiểm tra trường thông tin và duyệt trước khi sử dụng"]
            subtitle = "Mẫu dùng chung" if t.get("visibility") == "shared" else "Mẫu cá nhân"
            if not _matches_query(
                query_text,
                t.get("name"),
                subtitle,
                " ".join(reasons),
                " ".join(reason_codes),
            ):
                continue
            is_admin_shared = user.get("role") == "admin" and t.get("visibility") == "shared"
            target_prefix = "/admin/templates" if is_admin_shared else "/templates"
            items.append(
                {
                    "id": f"template:{t['_id']}",
                    "resource_type": "template",
                    "resource_id": t["_id"],
                    "title": t.get("name", ""),
                    "subtitle": subtitle,
                    "state": t.get("state", "pending"),
                    "target_url": f"{target_prefix}/{t['_id']}",
                    "target_tab": "review",
                    "reason_codes": reason_codes,
                    "reasons": reasons,
                    "review_count": 1,
                    "version_id": t.get("active_version_id"),
                    "updated_at": t.get("updated_at") or t.get("created_at", ""),
                }
            )

    items.sort(key=lambda x: (x.get("updated_at") or "", x.get("id") or ""), reverse=True)
    total = len(items)
    start = (page - 1) * limit
    return {
        "items": items[start : start + limit],
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.get("/documents")
def list_workspace_documents(
    q: str = Query("", max_length=200),
    review: Literal["all", "reviewed", "needs_review", "stale"] = "all",
    page: int = Query(1, ge=1),
    limit: int = Query(30, ge=1, le=100),
    user=Depends(current_user),
    mongo=Depends(database),
):
    owner_id = user["_id"]
    query_text = q.strip()

    meetings = list(
        mongo.db.meetings.find(
            {
                "owner_id": owner_id,
                "trashed": False,
                "active_minutes_id": {"$ne": None},
            }
        ).sort([("updated_at", -1), ("_id", 1)])
    )
    minutes_ids = [m["active_minutes_id"] for m in meetings if m.get("active_minutes_id")]
    versions_by_id: dict[str, dict] = {}
    template_ids: set[str] = set()
    if minutes_ids:
        for mv in mongo.db.minutes_versions.find({"_id": {"$in": minutes_ids}}):
            versions_by_id[mv["_id"]] = mv
            if mv.get("template_id"):
                template_ids.add(mv["template_id"])

    templates_by_id: dict[str, dict] = {}
    if template_ids:
        for t in mongo.db.templates.find(
            {"_id": {"$in": list(template_ids)}}, {"_id": 1, "name": 1}
        ):
            templates_by_id[t["_id"]] = t

    items: list[dict] = []
    for m in meetings:
        active_id = m.get("active_minutes_id")
        mv = versions_by_id.get(active_id)
        if not mv:
            continue
        mv_public = public(mv)
        is_stale = bool(
            m.get("minutes_stale") or mv.get("input_content_revision") != m.get("content_revision")
        )
        if is_stale:
            review_status = "stale"
        elif m.get("reviewed_version") == mv["_id"]:
            review_status = "reviewed"
        else:
            review_status = "needs_review"

        if review != "all" and review_status != review:
            continue

        template_id = mv.get("template_id")
        template_name = templates_by_id.get(template_id, {}).get("name") if template_id else None

        if not _matches_query(
            query_text,
            m.get("title"),
            m.get("location"),
            m.get("date"),
            template_name,
            mv["_id"],
        ):
            continue

        items.append(
            {
                "id": mv["_id"],
                "meeting_id": m["_id"],
                "meeting_title": m.get("title", ""),
                "meeting_date": m.get("date", ""),
                "meeting_location": m.get("location", ""),
                "version_id": mv["_id"],
                "created_at": mv.get("created_at", ""),
                "updated_at": m.get("updated_at") or mv.get("created_at", ""),
                "review_status": review_status,
                "minutes_stale": is_stale,
                "reviewed_version": m.get("reviewed_version"),
                "template_id": template_id,
                "template_name": template_name,
                "docx": mv_public.get("docx"),
                "zip": mv_public.get("zip"),
                "previews": mv_public.get("previews", []),
            }
        )

    items.sort(key=lambda x: (x.get("updated_at") or "", x.get("id") or ""), reverse=True)
    total = len(items)
    start = (page - 1) * limit
    return {
        "items": items[start : start + limit],
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.get("/jobs")
def list_workspace_jobs(
    q: str = Query("", max_length=200),
    state: str = Query("", max_length=60),
    kind: str = Query("", max_length=60),
    page: int = Query(1, ge=1),
    limit: int = Query(30, ge=1, le=100),
    user=Depends(current_user),
    mongo=Depends(database),
):
    owner_id = user["_id"]
    query_text = q.strip()
    state_filter = state.strip()
    kind_filter = kind.strip()

    mongo_query: dict = {"owner_id": owner_id}
    if state_filter and state_filter != "all":
        mongo_query["state"] = state_filter
    if kind_filter and kind_filter != "all":
        mongo_query["kind"] = kind_filter

    if query_text:
        pattern = {"$regex": re.escape(query_text), "$options": "i"}
        resource_ids = []
        for collection, field in [
            (mongo.db.meetings, "title"),
            (mongo.db.templates, "name"),
            (mongo.db.speakers, "name"),
        ]:
            resource_ids.extend(
                row["_id"]
                for row in collection.find({"owner_id": owner_id, field: pattern}, {"_id": 1})
            )
        mongo_query["$or"] = [
            {field: pattern} for field in ["kind", "stage", "state", "resource_id", "error.message"]
        ] + [{"resource_id": {"$in": resource_ids}}]
    total = mongo.db.jobs.count_documents(mongo_query)
    raw_jobs = list(
        mongo.db.jobs.find(mongo_query)
        .sort([("created_at", -1), ("_id", 1)])
        .skip((page - 1) * limit)
        .limit(limit)
    )

    meeting_ids = {j["resource_id"] for j in raw_jobs if j.get("resource_type") == "meeting"}
    template_ids = {j["resource_id"] for j in raw_jobs if j.get("resource_type") == "template"}
    speaker_ids = {j["resource_id"] for j in raw_jobs if j.get("resource_type") == "speaker"}

    resources: dict[tuple[str, str], dict] = {}
    if meeting_ids:
        for m in mongo.db.meetings.find(
            {"_id": {"$in": list(meeting_ids)}},
            {"_id": 1, "title": 1, "trashed": 1, "content_revision": 1, "active_job": 1},
        ):
            resources[("meeting", m["_id"])] = m
    if template_ids:
        for t in mongo.db.templates.find(
            {"_id": {"$in": list(template_ids)}},
            {"_id": 1, "name": 1, "trashed": 1, "content_revision": 1, "active_job": 1},
        ):
            resources[("template", t["_id"])] = t
    if speaker_ids:
        for s in mongo.db.speakers.find(
            {"_id": {"$in": list(speaker_ids)}},
            {"_id": 1, "name": 1, "trashed": 1, "content_revision": 1, "active_job": 1},
        ):
            resources[("speaker", s["_id"])] = s

    items: list[dict] = []
    for j in raw_jobs:
        view = job_service.job_view(j)
        rtype = j.get("resource_type", "")
        rid = j.get("resource_id", "")
        res = resources.get((rtype, rid))
        if rtype == "meeting":
            res_title = res.get("title") if res else None
        elif rtype in {"template", "speaker"}:
            res_title = res.get("name") if res else None
        else:
            res_title = "Hệ thống"

        allowed_actions: list[str] = []
        if j.get("state") in {"queued", "running"} and not j.get("cancel_requested"):
            allowed_actions.append("cancel")
        if (
            j.get("state") in {"failed", "interrupted", "cancelled"}
            and res
            and not res.get("trashed")
            and res.get("active_job") is None
            and res.get("content_revision", 0) == j.get("input_content_revision", 0)
        ):
            allowed_actions.append("retry")
        if res and not res.get("trashed") and rtype in {"meeting", "template", "speaker"}:
            allowed_actions.append("open_resource")

        view["resource_title"] = res_title or rid
        view["allowed_actions"] = allowed_actions
        items.append(view)

    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
    }
