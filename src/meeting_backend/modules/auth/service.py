from datetime import UTC, datetime, timedelta

from pymongo.errors import DuplicateKeyError

from meeting_backend.core.errors import AppError
from meeting_backend.core.security import digest, hash_password, token, verify_password
from meeting_backend.infrastructure.mongodb.client import new_id, now, public

DUMMY_HASH = hash_password("not-an-account-password")


def create_user(mongo, payload, actor_id=None):
    record = {
        "_id": new_id(),
        "username": payload.username.lower(),
        "display_name": payload.display_name.strip(),
        "role": payload.role,
        "active": True,
        "password_hash": hash_password(payload.password),
        "created_at": now(),
        "updated_at": now(),
    }
    if not record["display_name"]:
        raise AppError("INVALID_NAME", "Tên hiển thị không được để trống.", 422)
    try:
        mongo.db.users.insert_one(record)
    except DuplicateKeyError as exc:
        raise AppError("USERNAME_EXISTS", "Tên đăng nhập đã được sử dụng.", 409) from exc
    mongo.audit(actor_id or record["_id"], "user_created", record["_id"], role=record["role"])
    return public(record)


def setup(mongo, payload):
    if mongo.db.users.count_documents({}):
        raise AppError("SETUP_COMPLETE", "Hệ thống đã có tài khoản quản trị.", 409)
    try:
        mongo.db.settings.insert_one({"_id": "bootstrap_lock", "created_at": now()})
    except DuplicateKeyError as exc:
        raise AppError("SETUP_BUSY", "Thiết lập đang được thực hiện.", 409) from exc
    try:
        if mongo.db.users.count_documents({}):
            raise AppError("SETUP_COMPLETE", "Hệ thống đã có tài khoản quản trị.", 409)
        payload.role = "admin"
        return create_user(mongo, payload)
    finally:
        mongo.db.settings.delete_one({"_id": "bootstrap_lock"})


def login(mongo, payload, client_ip):
    cutoff = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    identifier = digest(client_ip + ":" + payload.username.lower())
    if (
        mongo.db.audit_events.count_documents(
            {
                "action": "login_failed",
                "details.identifier": identifier,
                "created_at": {"$gt": cutoff},
            }
        )
        >= 8
    ):
        raise AppError("LOGIN_LIMIT", "Đăng nhập sai nhiều lần. Hãy thử lại sau 10 phút.", 429)
    user = mongo.db.users.find_one({"username": payload.username.lower()})
    valid = verify_password(payload.password, user["password_hash"] if user else DUMMY_HASH)
    if not user or not valid or not user.get("active"):
        mongo.audit("anonymous", "login_failed", "", identifier=identifier)
        raise AppError("INVALID_CREDENTIALS", "Tên đăng nhập hoặc mật khẩu không đúng.", 401)
    raw, csrf = token(), token()
    mongo.db.sessions.insert_one(
        {
            "_id": new_id(),
            "user_id": user["_id"],
            "token_hash": digest(raw),
            "csrf_hash": digest(csrf),
            "expires_at": datetime.now(UTC) + timedelta(hours=mongo.settings.session_hours),
            "created_at": now(),
        }
    )
    mongo.audit(user["_id"], "login", user["_id"])
    return public(user), raw, csrf
