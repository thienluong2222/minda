"""FastAPI entry point. Startup reads MongoDB and registers routes; inference is worker-only."""

import logging
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pymongo.errors import PyMongoError

from meeting_backend.api.dependencies import current_user, database
from meeting_backend.core.errors import AppError
from meeting_backend.core.logging import RedactingFormatter
from meeting_backend.core.settings import Settings
from meeting_backend.infrastructure.artifacts.store import ArtifactStore
from meeting_backend.infrastructure.mongodb.client import Mongo

logger = logging.getLogger("meeting_backend")


def create_app(settings: Settings | None = None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        log_dir = settings.data_dir / "logs"
        log_dir.mkdir(exist_ok=True)
        handler = logging.FileHandler(log_dir / "api.log", encoding="utf-8")
        handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        mongo = Mongo(settings)
        mongo.initialize()
        app.state.mongo = mongo
        try:
            yield
        finally:
            mongo.close()
            logger.removeHandler(handler)
            handler.close()

    app = FastAPI(title="Minda API", version="1.0.0", lifespan=lifespan)
    app.state.settings = settings

    @app.exception_handler(AppError)
    async def application_error(request, exc):
        return JSONResponse(
            {
                "error": {"code": exc.code, "message": exc.message},
                "request_id": getattr(request.state, "request_id", None),
            },
            status_code=exc.status,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse(
            {
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Dữ liệu không hợp lệ.",
                    "fields": [
                        {"field": ".".join(map(str, e["loc"])), "message": e["msg"]}
                        for e in exc.errors()
                    ],
                },
                "request_id": getattr(request.state, "request_id", None),
            },
            status_code=422,
        )

    @app.exception_handler(PyMongoError)
    async def database_error(request, exc):
        logger.exception("MongoDB error request_id=%s", getattr(request.state, "request_id", None))
        return JSONResponse(
            {
                "error": {
                    "code": "DATABASE_ERROR",
                    "message": "Không thể hoàn tất thao tác với database. Hãy thử lại.",
                }
            },
            status_code=503,
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        logger.exception(
            "Unhandled error request_id=%s", getattr(request.state, "request_id", None)
        )
        return JSONResponse(
            {
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "Có lỗi xử lý. Hãy tra log bằng mã yêu cầu.",
                },
                "request_id": getattr(request.state, "request_id", None),
            },
            status_code=500,
        )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = str(uuid4())
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            own = str(request.base_url).rstrip("/")
            if origin and origin not in [own, *settings.allowed_origins]:
                return JSONResponse(
                    {
                        "error": {
                            "code": "ORIGIN_REJECTED",
                            "message": "Nguồn yêu cầu không hợp lệ.",
                        }
                    },
                    status_code=403,
                )
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        logger.info(
            "request_id=%s method=%s path=%s status=%s elapsed=%.3f",
            request.state.request_id,
            request.method,
            request.url.path,
            response.status_code,
            time.perf_counter() - started,
        )
        return response

    from meeting_backend.modules.auth.router import router as auth
    from meeting_backend.modules.jobs.router import router as jobs
    from meeting_backend.modules.meetings.admin import router as admin_meetings
    from meeting_backend.modules.meetings.router import router as meetings
    from meeting_backend.modules.minutes.router import router as minutes
    from meeting_backend.modules.speakers.router import router as speakers
    from meeting_backend.modules.system.router import router as system
    from meeting_backend.modules.templates.router import router as templates
    from meeting_backend.modules.transcripts.router import router as transcripts
    from meeting_backend.modules.users.router import router as users

    for router in [
        auth,
        users,
        meetings,
        admin_meetings,
        jobs,
        transcripts,
        minutes,
        templates,
        speakers,
        system,
    ]:
        app.include_router(router, prefix="/api/v1")

    @app.get("/api/v1/health")
    def health(mongo=Depends(database)):
        mongo.client.admin.command("ping")
        return {"status": "ok", "database": "mongodb", "api_version": "v1"}

    @app.get("/api/v1/artifacts/{artifact_id}")
    def artifact(
        artifact_id: str,
        download: bool = False,
        user=Depends(current_user),
        mongo=Depends(database),
    ):
        record = mongo.db.artifacts.find_one({"_id": artifact_id})
        if not record:
            raise AppError("NOT_FOUND", "Không tìm thấy file.", 404)
        allowed = record["owner_id"] == user["_id"]
        if not allowed and record.get("resource_id"):
            template = mongo.db.templates.find_one(
                {"_id": record["resource_id"], "visibility": "shared", "trashed": False}
            )
            allowed = bool(template)
        if not allowed:
            raise AppError("NOT_FOUND", "Không tìm thấy file.", 404)
        store = ArtifactStore(mongo)
        return FileResponse(
            store.resolve(record),
            media_type=record["media_type"],
            filename=record["name"] if download else None,
            content_disposition_type="attachment" if download else "inline",
        )

    if settings.web_dist.is_dir():
        assets = settings.web_dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def frontend(path: str):
            if path.startswith("api/"):
                raise AppError("NOT_FOUND", "API không tồn tại.", 404)
            return FileResponse(settings.web_dist / "index.html")

    return app
