import re
from typing import Literal

from fastapi import APIRouter, Depends, Query

from meeting_backend.api.dependencies import administrator, current_user, database
from meeting_backend.core.errors import AppError
from meeting_backend.core.security import hash_password, verify_password
from meeting_backend.infrastructure.mongodb.client import now, public
from meeting_backend.modules.auth.schemas import CreateUser, PasswordChange, UserUpdate
from meeting_backend.modules.auth.service import create_user

router = APIRouter(tags=["users"])


@router.get("/admin/users")
def list_users(
    q: str = Query("", max_length=200),
    role: Literal["user", "admin"] | None = None,
    active: bool | None = None,
    user=Depends(administrator),
    mongo=Depends(database),
):
    query = {}
    if q.strip():
        pattern = {"$regex": re.escape(q.strip()), "$options": "i"}
        query["$or"] = [{"username": pattern}, {"display_name": pattern}]
    if role is not None:
        query["role"] = role
    if active is not None:
        query["active"] = active
    users = list(mongo.db.users.find(query).sort([("created_at", -1), ("_id", 1)]))
    counts = {}
    for group in mongo.db.meetings.aggregate(
        [
            {"$match": {"owner_id": {"$in": [account["_id"] for account in users]}}},
            {
                "$group": {
                    "_id": {"owner_id": "$owner_id", "trashed": "$trashed"},
                    "count": {"$sum": 1},
                }
            },
        ]
    ):
        owner = counts.setdefault(group["_id"]["owner_id"], {"active": 0, "trashed": 0})
        owner["trashed" if group["_id"].get("trashed") else "active"] += group["count"]
    return [
        {
            **public(account),
            "meeting_count": counts.get(account["_id"], {}).get("active", 0),
            "trashed_meeting_count": counts.get(account["_id"], {}).get("trashed", 0),
        }
        for account in users
    ]


@router.post("/admin/users", status_code=201)
def add_user(payload: CreateUser, user=Depends(administrator), mongo=Depends(database)):
    return create_user(mongo, payload, user["_id"])


@router.patch("/admin/users/{user_id}")
def update_user(
    user_id: str, payload: UserUpdate, user=Depends(administrator), mongo=Depends(database)
):
    changes = payload.model_dump(exclude_none=True)
    if user_id == user["_id"] and (changes.get("active") is False or changes.get("role") == "user"):
        raise AppError(
            "SELF_LOCKOUT", "Hãy dùng tài khoản quản trị khác để đổi quyền tài khoản này.", 409
        )
    result = mongo.db.users.update_one({"_id": user_id}, {"$set": {**changes, "updated_at": now()}})
    if not result.matched_count:
        raise AppError("NOT_FOUND", "Không tìm thấy tài khoản.", 404)
    mongo.audit(user["_id"], "user_updated", user_id, changes=changes)
    return public(mongo.db.users.find_one({"_id": user_id}))


@router.post("/users/{user_id}/password")
def password(
    user_id: str, payload: PasswordChange, user=Depends(current_user), mongo=Depends(database)
):
    own = user_id == user["_id"]
    if not own and user["role"] != "admin":
        raise AppError("FORBIDDEN", "Không có quyền thay mật khẩu.", 403)
    if own and not verify_password(payload.current_password or "", user["password_hash"]):
        raise AppError("INVALID_PASSWORD", "Mật khẩu hiện tại không đúng.", 422)
    result = mongo.db.users.update_one(
        {"_id": user_id},
        {"$set": {"password_hash": hash_password(payload.password), "updated_at": now()}},
    )
    if not result.matched_count:
        raise AppError("NOT_FOUND", "Không tìm thấy tài khoản.", 404)
    mongo.db.sessions.delete_many({"user_id": user_id})
    mongo.audit(user["_id"], "password_reset", user_id)
    return {"status": "ok", "reauthenticate": True}
