"""Authentication, CSRF and role dependencies shared by all resource endpoints."""

import secrets
from datetime import UTC, datetime

from fastapi import Depends, Request

from meeting_backend.core.errors import AppError
from meeting_backend.core.security import COOKIE, digest


def database(request: Request):
    return request.app.state.mongo


def current_user(request: Request, mongo=Depends(database)):
    raw = request.cookies.get(COOKIE, "")
    session = mongo.db.sessions.find_one({"token_hash": digest(raw)}) if raw else None
    if not session or session["expires_at"] <= datetime.now(UTC):
        raise AppError("UNAUTHENTICATED", "Vui lòng đăng nhập.", 401)
    user = mongo.db.users.find_one({"_id": session["user_id"], "active": True})
    if not user:
        raise AppError("UNAUTHENTICATED", "Phiên đăng nhập không còn hợp lệ.", 401)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        sent = request.headers.get("X-CSRF-Token", "")
        if not sent or not secrets.compare_digest(digest(sent), session["csrf_hash"]):
            raise AppError("CSRF_REJECTED", "Yêu cầu không hợp lệ. Hãy tải lại trang.", 403)
    request.state.user_id = user["_id"]
    return user


def administrator(user=Depends(current_user)):
    if user["role"] != "admin":
        raise AppError("FORBIDDEN", "Chức năng dành cho quản trị viên.", 403)
    return user
