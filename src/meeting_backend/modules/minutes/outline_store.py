"""Immutable, paginated editorial plans scoped to the saved minutes version."""

import json
from pathlib import Path

from pymongo import UpdateOne

from meeting_backend.core.errors import AppError
from meeting_pipeline.minutes.graph_contracts import digest
from meeting_pipeline.minutes.graph_plan import ContentPlan


def persist_outline(mongo, meeting, version_id, plan):
    if not plan or plan.get("schema_version") not in {"2.0", "3.0"}:
        return None
    scope = {
        "owner_id": meeting["owner_id"],
        "meeting_id": meeting["_id"],
        "version_id": version_id,
    }
    count = 0
    sections = list(plan.get("sections", []))
    review = plan.get("review_items", [])
    if review:
        sections.append(
            {
                "section_id": "review",
                "title": "Nội dung cần đối chiếu",
                "summary": "Các đoạn chưa rõ được giữ lại để rà soát, chưa đưa vào nội dung chính.",
                "outline": [
                    {
                        "item_id": row["claim_id"],
                        "role": "unresolved",
                        "text": row.get("text", "Đoạn lời chép chưa rõ"),
                        "claim_ids": [row["claim_id"]],
                        "evidence_ids": row["unit_ids"],
                        "verification": "needs_review",
                    }
                    for row in review
                ],
            }
        )
    operations = []
    for index, section in enumerate(sections):
        section_id = section["section_id"]
        items = section.get("outline", [])
        paragraphs = section.get("paragraphs", [])
        statuses = {p.get("verification") for p in paragraphs}
        record = {
            **scope,
            "section_id": section_id,
            "index": index,
            "title": section["title"],
            "summary": section.get("summary", ""),
            "topic_id": section.get("topic_id"),
            "topic_ids": section.get("topic_ids", []),
            "item_count": len(items),
            "is_review": section_id == "review",
            "writing_status": "checked" if statuses == {"checked"} else "needs_review",
        }
        mongo.db.meeting_outline_sections.update_one(
            {"_id": digest([scope, section_id])},
            {"$setOnInsert": record},
            upsert=True,
        )
        for position, item in enumerate(items):
            operations.append(
                UpdateOne(
                    {"_id": digest([scope, section_id, item["item_id"]])},
                    {
                        "$setOnInsert": {
                            **scope,
                            "section_id": section_id,
                            "index": position,
                            "value": item,
                        }
                    },
                    upsert=True,
                )
            )
            if len(operations) >= 500:
                mongo.db.meeting_outline_items.bulk_write(operations, ordered=False)
                operations = []
        count += len(items)
    if operations:
        mongo.db.meeting_outline_items.bulk_write(operations, ordered=False)
    return {
        "schema_version": plan["schema_version"],
        "plan_id": plan.get("plan_id"),
        "parent_plan_id": plan.get("parent_plan_id"),
        "section_count": len(sections),
        "item_count": count,
        "review_count": len(review),
    }


def load_editable_plan(mongo, meeting, version) -> tuple[Path, ContentPlan]:
    if not version or (version.get("outline") or {}).get("schema_version") != "3.0":
        raise AppError("OUTLINE_UPGRADE_REQUIRED", "Hãy tạo lại biên bản để chỉnh dàn ý.", 409)
    if version["transcript_version_id"] != meeting.get("active_transcript_id") or version[
        "input_content_revision"
    ] != meeting.get("content_revision"):
        raise AppError("OUTLINE_STALE", "Lời chép đã thay đổi. Hãy tạo lại biên bản.", 409)
    run = Path(version["run_path"]).resolve()
    if not run.is_relative_to(mongo.settings.data_dir.resolve()):
        raise AppError("INVALID_PATH", "Phiên bản nguồn không hợp lệ.")
    plan = ContentPlan.model_validate(json.loads((run / "minutes/content_plan.json").read_text()))
    if (
        plan.plan_id != version["outline"]["plan_id"]
        or plan.graph_id != version["graph_id"]
        or plan.transcript_version_id != version["transcript_version_id"]
        or plan.phase != "written"
    ):
        raise AppError("OUTLINE_STALE", "Dàn ý không khớp với phiên bản biên bản.", 409)
    return run, plan


def outline_page(mongo, scope, page, limit):
    query = mongo.db.meeting_outline_sections.find(scope).sort("index", 1)
    rows = list(query.skip((page - 1) * limit).limit(limit))
    return {
        "items": [
            {
                k: v
                for k, v in section.items()
                if k not in {"_id", "owner_id", "meeting_id", "version_id"}
            }
            | {
                "items": [
                    row["value"]
                    for row in mongo.db.meeting_outline_items.find(
                        {**scope, "section_id": section["section_id"]}
                    )
                    .sort("index", 1)
                    .limit(6)
                ],
            }
            for section in rows
        ],
        "total": mongo.db.meeting_outline_sections.count_documents(scope),
        "page": page,
        "limit": limit,
    }
