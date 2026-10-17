from pymongo import ReturnDocument

from meeting_backend.core.errors import AppError
from meeting_backend.infrastructure.mongodb.client import now
from meeting_backend.infrastructure.mongodb.repository import Repository


class MeetingRepository(Repository):
    collection_name = "meetings"

    def editable(self, meeting_id, user, revision):
        meeting = self.owned(meeting_id, user)
        if meeting.get("trashed"):
            raise AppError("MEETING_TRASHED", "Hãy khôi phục cuộc họp trước khi chỉnh sửa.", 409)
        if meeting.get("active_job"):
            raise AppError("RESOURCE_BUSY", "Cuộc họp đang được xử lý.", 409)
        if revision != meeting["revision"]:
            raise AppError(
                "REVISION_CONFLICT", "Dữ liệu đã thay đổi. Hãy tải lại trước khi lưu.", 409
            )
        return meeting

    def update(self, meeting, changes, *, content_changed=False):
        increments = {"revision": 1}
        if content_changed:
            increments["content_revision"] = 1
            changes = {**changes, "minutes_stale": bool(meeting.get("active_minutes_id"))}
        updated = self.collection.find_one_and_update(
            {"_id": meeting["_id"], "revision": meeting["revision"], "active_job": None},
            {"$set": {**changes, "updated_at": now()}, "$inc": increments},
            return_document=ReturnDocument.AFTER,
        )
        if not updated:
            raise AppError("REVISION_CONFLICT", "Dữ liệu đã thay đổi hoặc đang xử lý.", 409)
        return updated
