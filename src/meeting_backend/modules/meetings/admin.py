"""System-wide meeting metadata for administrators, without private document access."""

import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from meeting_backend.api.dependencies import administrator, database
from meeting_backend.infrastructure.mongodb.client import Mongo

router = APIRouter(prefix="/admin/meetings", tags=["admin meetings"])


@router.get("")
def list_meetings(
    user: Annotated[dict, Depends(administrator)],
    mongo: Annotated[Mongo, Depends(database)],
    q: Annotated[str, Query(max_length=200)] = "",
    owner_id: str = "",
    state: Literal["", "draft", "processing", "transcript_ready", "minutes_ready"] = "",
    trashed: Literal["active", "trashed", "all"] = "active",
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
):
    query = {}
    if trashed != "all":
        query["trashed"] = trashed == "trashed"
    if owner_id:
        query["owner_id"] = owner_id
    if state == "processing":
        query["active_job"] = {"$ne": None}
    elif state:
        query["state"] = state
    if q.strip():
        pattern = {"$regex": re.escape(q.strip()), "$options": "i"}
        owners = mongo.db.users.find(
            {"$or": [{"username": pattern}, {"display_name": pattern}]}, {"_id": 1}
        )
        query["$or"] = [
            {"title": pattern},
            {"owner_id": {"$in": [owner["_id"] for owner in owners]}},
        ]
    # Project only management metadata, not notes, paths, transcript or file references.
    projection = {
        field: 1
        for field in [
            "title",
            "owner_id",
            "date",
            "location",
            "state",
            "trashed",
            "created_at",
            "updated_at",
            "source_ids",
            "active_job",
            "active_transcript_id",
            "active_minutes_id",
            "minutes_stale",
        ]
    }
    meetings = list(
        mongo.db.meetings.find(query, projection)
        .sort([("updated_at", -1), ("_id", 1)])
        .skip((page - 1) * limit)
        .limit(limit)
    )
    owners = {
        owner["_id"]: owner
        for owner in mongo.db.users.find(
            {"_id": {"$in": list({meeting["owner_id"] for meeting in meetings})}},
            {"display_name": 1, "username": 1},
        )
    }
    items = []
    for meeting in meetings:
        owner = owners.get(meeting["owner_id"], {})
        items.append(
            {
                "id": meeting["_id"],
                "title": meeting.get("title", ""),
                "owner_id": meeting["owner_id"],
                "owner_name": owner.get("display_name", "Tài khoản không còn tồn tại"),
                "owner_username": owner.get("username", ""),
                "date": meeting.get("date", ""),
                "location": meeting.get("location", ""),
                "state": meeting.get("state", "draft"),
                "trashed": bool(meeting.get("trashed")),
                "created_at": meeting.get("created_at", ""),
                "updated_at": meeting.get("updated_at", ""),
                "source_count": len(meeting.get("source_ids") or []),
                "active_job": meeting.get("active_job"),
                "has_transcript": bool(meeting.get("active_transcript_id")),
                "has_minutes": bool(meeting.get("active_minutes_id")),
                "minutes_stale": bool(meeting.get("minutes_stale")),
            }
        )
    return {
        "items": items,
        "total": mongo.db.meetings.count_documents(query),
        "page": page,
        "limit": limit,
    }
