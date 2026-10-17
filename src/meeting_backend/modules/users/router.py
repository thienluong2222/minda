from fastapi import APIRouter, Depends

from meeting_backend.api.dependencies import administrator, current_user, database
from meeting_backend.core.errors import AppError
from meeting_backend.core.security import hash_password, verify_password
from meeting_backend.infrastructure.mongodb.client import now, public
from meeting_backend.modules.auth.schemas import CreateUser, PasswordChange, UserUpdate
from meeting_backend.modules.auth.service import create_user

router = APIRouter(tags=["users"])


@router.get("/admin/users")
def list_users(user=Depends(administrator), mongo=Depends(database)):
    return [public(u) for u in mongo.db.users.find().sort("created_at", -1)]


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
