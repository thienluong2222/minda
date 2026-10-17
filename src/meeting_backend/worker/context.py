"""Worker context with lease fencing, cancellation checks and conditional publication."""

import logging
from datetime import UTC, datetime
from pathlib import Path

from pymongo import ReturnDocument

from meeting_backend.infrastructure.artifacts.store import ArtifactStore
from meeting_backend.infrastructure.mongodb.client import now
from meeting_backend.modules.jobs.service import RESOURCE_COLLECTIONS


class Cancelled(Exception):
    pass


class Context:
    def __init__(self, mongo, job):
        self.mongo, self.job = mongo, job
        self.store = ArtifactStore(mongo)
        self.root = mongo.settings.data_dir
        self.staging = self.root / "staging" / job["_id"]
        self.staging.mkdir(parents=True, exist_ok=True)
        self.resource_collection = mongo.db[RESOURCE_COLLECTIONS[job["resource_type"]]]
        self.published = False
        self.result = {}
        self.logger = logging.getLogger("meeting_backend.worker")

    def check(self):
        current = self.mongo.db.jobs.find_one(
            {
                "_id": self.job["_id"],
                "state": "running",
                "lease_token": self.job["lease_token"],
                "lease_until": {"$gt": datetime.now(UTC)},
            }
        )
        if not current or current.get("cancel_requested"):
            raise Cancelled("Tác vụ đã bị hủy hoặc worker không còn quyền xử lý.")

    def stage(self, message):
        self.check()
        self.mongo.db.jobs.update_one(
            {"_id": self.job["_id"], "lease_token": self.job["lease_token"]},
            {"$set": {"stage": message, "updated_at": now()}},
        )
        self.logger.info(
            "job_id=%s resource_id=%s stage=%s", self.job["_id"], self.job["resource_id"], message
        )

    def resource(self):
        self.check()
        record = self.resource_collection.find_one(
            {
                "_id": self.job["resource_id"],
                "owner_id": self.job["owner_id"],
                "active_job": self.job["_id"],
            }
        )
        if not record:
            raise Cancelled("Tài nguyên không còn thuộc tác vụ này.")
        return record

    def publish(self, changes, *, content_changed=False, result=None):
        self.check()
        increments = {"revision": 1}
        if content_changed:
            increments["content_revision"] = 1
        updated = self.resource_collection.find_one_and_update(
            {"_id": self.job["resource_id"], "active_job": self.job["_id"]},
            {
                "$set": {
                    **changes,
                    "active_job": None,
                    "last_job_id": self.job["_id"],
                    "updated_at": now(),
                },
                "$inc": increments,
            },
            return_document=ReturnDocument.AFTER,
        )
        if not updated:
            raise Cancelled("Tài nguyên đã thay đổi trước khi công bố.")
        self.published = True
        self.result = result or {}
        return updated

    def artifact(self, path, *, name=None, visibility="private"):
        return self.store.view(
            self.store.register(
                Path(path),
                self.job["owner_id"],
                name=name,
                visibility=visibility,
                resource_id=self.job["resource_id"],
            )
        )
