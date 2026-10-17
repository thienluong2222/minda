from fastapi import APIRouter, Depends, Request, Response

from meeting_backend.api.dependencies import current_user, database
from meeting_backend.core.security import COOKIE, CSRF_COOKIE, digest
from meeting_backend.infrastructure.mongodb.client import public
from meeting_backend.modules.auth import service
from meeting_backend.modules.auth.schemas import CreateUser, Login

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/status")
def status(mongo=Depends(database)):
    return {"requires_setup": mongo.db.users.count_documents({}) == 0}


@router.post("/setup", status_code=201)
def setup(payload: CreateUser, mongo=Depends(database)):
    return service.setup(mongo, payload)


@router.post("/login")
def login(payload: Login, request: Request, response: Response, mongo=Depends(database)):
    user, raw, csrf = service.login(
        mongo, payload, request.client.host if request.client else "local"
    )
    options = {
        "secure": mongo.settings.cookie_secure,
        "samesite": "strict",
        "path": "/",
        "max_age": mongo.settings.session_hours * 3600,
    }
    response.set_cookie(COOKIE, raw, httponly=True, **options)
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, **options)
    return user


@router.get("/me")
def me(user=Depends(current_user)):
    return public(user)


@router.post("/logout")
def logout(
    request: Request, response: Response, user=Depends(current_user), mongo=Depends(database)
):
    mongo.db.sessions.delete_one({"token_hash": digest(request.cookies.get(COOKIE, ""))})
    response.delete_cookie(COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"status": "ok"}
