"""One durable worker per data root, with MongoDB leases and cooperative cancellation."""

import fcntl
import gc
import logging
import os
import signal
import sys
import threading
from datetime import UTC, datetime, timedelta

from pymongo import ReturnDocument

from meeting_backend.core.errors import AppError
from meeting_backend.core.logging import RedactingFormatter
from meeting_backend.infrastructure.mongodb.client import new_id, now
from meeting_backend.modules.jobs.service import RESOURCE_COLLECTIONS
from meeting_backend.worker.context import Cancelled, Context

logger = logging.getLogger("meeting_backend.worker")


class Runner:
    def __init__(self, mongo):
        self.mongo = mongo
        self.worker_id = new_id()
        self.stop = threading.Event()
        self.mongo.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.mongo.settings.data_dir / ".worker.lock"

    def recover(self):
        expired = list(
            self.mongo.db.jobs.find({"state": "running", "lease_until": {"$lt": datetime.now(UTC)}})
        )
        for job in expired:
            resource = self.mongo.db[RESOURCE_COLLECTIONS[job["resource_type"]]].find_one(
                {"_id": job["resource_id"]}
            )
            published = bool(resource and resource.get("last_job_id") == job["_id"])
            self.mongo.db.jobs.update_one(
                {"_id": job["_id"], "state": "running", "lease_token": job.get("lease_token")},
                {
                    "$set": {
                        "state": "succeeded" if published else "interrupted",
                        "completed_at": now(),
                        "stage": "Đã khôi phục trạng thái hoàn tất"
                        if published
                        else "Worker bị gián đoạn",
                        "error": None
                        if published
                        else {
                            "code": "WORKER_LOST",
                            "message": "Worker đã dừng khi xử lý. Có thể thử lại.",
                        },
                    }
                },
            )
            self.mongo.db[RESOURCE_COLLECTIONS[job["resource_type"]]].update_one(
                {"_id": job["resource_id"], "active_job": job["_id"]},
                {"$set": {"active_job": None}, "$inc": {"revision": 1}},
            )
        # Recover a crash between resource claim and inserting its queue record.
        for name in RESOURCE_COLLECTIONS.values():
            for resource in self.mongo.db[name].find({"active_job": {"$type": "string"}}):
                if not self.mongo.db.jobs.find_one({"_id": resource["active_job"]}):
                    self.mongo.db[name].update_one(
                        {"_id": resource["_id"], "active_job": resource["active_job"]},
                        {"$set": {"active_job": None}, "$inc": {"revision": 1}},
                    )

    def heartbeat(self, job, done):
        while not done.wait(5):
            try:
                self.mongo.db.jobs.update_one(
                    {"_id": job["_id"], "state": "running", "lease_token": job["lease_token"]},
                    {
                        "$set": {
                            "lease_until": datetime.now(UTC)
                            + timedelta(seconds=self.mongo.settings.lease_seconds),
                            "heartbeat_at": now(),
                        }
                    },
                )
                self.mongo.db.settings.update_one(
                    {"_id": "worker_heartbeat"},
                    {
                        "$set": {
                            "last_seen": now(),
                            "worker_id": self.worker_id,
                            "active_job": job["_id"],
                        }
                    },
                    upsert=True,
                )
            except Exception:
                logger.exception("Heartbeat failed job_id=%s", job["_id"])

    def run_once(self):
        with self.lock_path.open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            try:
                return self._run_once()
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _run_once(self):
        self.recover()
        self.mongo.db.settings.update_one(
            {"_id": "worker_heartbeat"},
            {"$set": {"last_seen": now(), "worker_id": self.worker_id, "active_job": None}},
            upsert=True,
        )
        job = self.mongo.db.jobs.find_one_and_update(
            {"state": "queued"},
            {
                "$set": {
                    "state": "running",
                    "started_at": now(),
                    "heartbeat_at": now(),
                    "worker_id": self.worker_id,
                    "lease_token": new_id(),
                    "lease_until": datetime.now(UTC)
                    + timedelta(seconds=self.mongo.settings.lease_seconds),
                }
            },
            sort=[("created_at", 1)],
            return_document=ReturnDocument.AFTER,
        )
        if not job:
            return False
        directory = self.mongo.settings.data_dir / "logs/jobs" / job["_id"]
        directory.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(directory / "worker.log", encoding="utf-8")
        handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        root = logging.getLogger()
        root.addHandler(handler)
        previous_level = root.level
        root.setLevel(logging.INFO)
        context = Context(self.mongo, job)
        done = threading.Event()
        thread = threading.Thread(target=self.heartbeat, args=(job, done), daemon=True)
        thread.start()
        state, error = "succeeded", None
        try:
            user = self.mongo.db.users.find_one({"_id": job["owner_id"], "active": True})
            if not user:
                raise AppError("ACCOUNT_INACTIVE", "Tài khoản không còn hoạt động.", 403)
            kind = job["kind"]
            if kind in {"transcribe", "enroll_voice"}:
                import torch

                from meeting_backend.integrations.audio_pipeline import enroll_voice, transcribe

                torch.set_num_threads(2)
                (transcribe if kind == "transcribe" else enroll_voice)(context)
            elif kind in {"generate_minutes", "edit_facts", "format_minutes", "restore_minutes"}:
                from meeting_backend.integrations.minutes_pipeline import run_minutes

                run_minutes(context)
            elif kind in {"ingest_template", "review_template"}:
                from meeting_backend.processing.documents.ingest import run_template

                run_template(context)
            elif kind in {"backup_system", "restore_system"}:
                from meeting_backend.infrastructure.artifacts.backup import run_backup

                run_backup(context)
            else:
                raise AppError("UNKNOWN_JOB", "Loại tác vụ không được hỗ trợ.", 422)
            if not context.published:
                raise RuntimeError("Handler chưa công bố kết quả.")
        except Cancelled:
            state = "cancelled"
            logger.info("Cancelled job_id=%s", job["_id"])
        except Exception as exc:
            state = "failed"
            error = {
                "code": exc.code if isinstance(exc, AppError) else "PIPELINE_ERROR",
                "message": str(exc).replace(str(self.mongo.settings.data_dir), "[dữ liệu]")[:1500],
            }
            logger.exception("Failed job_id=%s stage=%s", job["_id"], job["kind"])
        finally:
            done.set()
            thread.join(timeout=10)
            self.mongo.db.jobs.update_one(
                {"_id": job["_id"], "state": "running", "lease_token": job["lease_token"]},
                {
                    "$set": {
                        "state": state,
                        "completed_at": now(),
                        "updated_at": now(),
                        "stage": {
                            "succeeded": "Hoàn tất",
                            "failed": "Xử lý thất bại",
                            "cancelled": "Đã hủy",
                        }[state],
                        "error": error,
                        "result": context.result,
                    }
                },
            )
            self.mongo.db[RESOURCE_COLLECTIONS[job["resource_type"]]].update_one(
                {"_id": job["resource_id"], "active_job": job["_id"]},
                {"$set": {"active_job": None}, "$inc": {"revision": 1}},
            )
            self.mongo.audit(
                job["owner_id"],
                "job_" + state,
                job["resource_id"],
                job_id=job["_id"],
                kind=job["kind"],
            )
            self.mongo.db.settings.update_one(
                {"_id": "worker_heartbeat"},
                {"$set": {"last_seen": now(), "active_job": None}},
                upsert=True,
            )
            root.removeHandler(handler)
            handler.close()
            root.setLevel(previous_level)
            gc.collect()
            if "torch" in sys.modules:
                import torch

                if torch.backends.mps.is_available():
                    torch.mps.empty_cache()
        return True

    def run_forever(self):
        for name in ["HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_IMPLICIT_TOKEN"]:
            os.environ[name] = "1"
        for sig in [signal.SIGINT, signal.SIGTERM]:
            signal.signal(sig, lambda *_: self.stop.set())
        while not self.stop.is_set():
            try:
                if not self.run_once():
                    self.stop.wait(2)
            except Exception:
                logger.exception("Worker loop error")
                self.stop.wait(3)
