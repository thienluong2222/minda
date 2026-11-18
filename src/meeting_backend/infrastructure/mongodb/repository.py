"""Small shared CRUD primitives; feature queries live in their own repositories."""

from meeting_backend.core.errors import AppError
from meeting_backend.infrastructure.mongodb.client import new_id, now


class Repository:
    collection_name = ""

    def __init__(self, mongo):
        self.mongo = mongo
        self.collection = mongo.db[self.collection_name]

    def get(self, record_id: str):
        result = self.collection.find_one({"_id": record_id})
        if result is None:
            raise AppError("NOT_FOUND", "Không tìm thấy dữ liệu.", 404)
        return result

    def owned(self, record_id: str, user, *, allow_shared=False):
        result = self.get(record_id)
        if result.get("owner_id") != user["_id"]:
            if not (allow_shared and result.get("visibility") == "shared"):
                raise AppError("NOT_FOUND", "Không tìm thấy dữ liệu.", 404)
        return result

    def create(self, **fields):
        record = {"_id": new_id(), "created_at": now(), "updated_at": now(), **fields}
        self.collection.insert_one(record)
        return record

    def list_owned(self, user, **filters):
        return list(
            self.collection.find({"owner_id": user["_id"], **filters}).sort("created_at", -1)
        )
