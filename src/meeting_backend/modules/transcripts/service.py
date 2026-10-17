"""Immutable transcript revisions, evidence-preserving edits and speaker renames."""

from copy import deepcopy

from meeting_backend.core.errors import AppError
from meeting_backend.infrastructure.mongodb.client import new_id, now, public
from meeting_backend.modules.meetings.repository import MeetingRepository


def rows_for(mongo, version_id):
    return list(mongo.db.transcript_segments.find({"version_id": version_id}).sort("index", 1))


def create_version(mongo, meeting, rows, *, reason, run_path=None):
    version = {
        "_id": new_id(),
        "meeting_id": meeting["_id"],
        "owner_id": meeting["owner_id"],
        "created_at": now(),
        "reason": reason,
        "segment_count": len(rows),
        "content_revision": meeting.get("content_revision", 0) + 1,
        "run_path": run_path,
        "parent_id": meeting.get("active_transcript_id"),
    }
    mongo.db.transcript_versions.insert_one(version)
    documents = []
    for index, row in enumerate(rows):
        item = deepcopy(row)
        item.update(
            _id=new_id(),
            version_id=version["_id"],
            meeting_id=meeting["_id"],
            owner_id=meeting["owner_id"],
            index=index,
        )
        documents.append(item)
    if documents:
        mongo.db.transcript_segments.insert_many(documents)
    return version


def discard_version(mongo, version_id):
    mongo.db.transcript_segments.delete_many({"version_id": version_id})
    mongo.db.transcript_versions.delete_one({"_id": version_id})


def view_row(row):
    return {key: value for key, value in public(row).items() if key not in {"data"}}


def edit(mongo, user, meeting_id, payload):
    repo = MeetingRepository(mongo)
    meeting = repo.editable(meeting_id, user, payload.revision)
    rows = rows_for(mongo, meeting.get("active_transcript_id"))
    target = next((r for r in rows if r["_id"] == payload.segment_id), None)
    if not target:
        raise AppError("NOT_FOUND", "Không tìm thấy đoạn hội thoại.", 404)
    target["text"] = payload.text.strip()
    target["user_edited"] = True
    target.setdefault("data", {})["text"] = target["text"]
    target["data"]["user_edited"] = True
    version = create_version(
        mongo,
        meeting,
        rows,
        reason="Sửa transcript",
        run_path=mongo.db.transcript_versions.find_one(
            {"_id": meeting["active_transcript_id"]}
        ).get("run_path"),
    )
    try:
        result = repo.update(
            meeting, {"active_transcript_id": version["_id"]}, content_changed=True
        )
    except BaseException:
        discard_version(mongo, version["_id"])
        raise
    mongo.audit(
        user["_id"],
        "transcript_edited",
        meeting_id,
        version_id=version["_id"],
        turn_id=target.get("turn_id"),
    )
    return public(result)


def rename(mongo, user, meeting_id, payload):
    repo = MeetingRepository(mongo)
    meeting = repo.editable(meeting_id, user, payload.revision)
    rows = rows_for(mongo, meeting.get("active_transcript_id"))
    targets = [
        r
        for r in rows
        if r.get("speaker_key") == payload.speaker_key and r.get("speaker_count", 1) == 1
    ]
    if not targets:
        raise AppError("NOT_FOUND", "Không tìm thấy người nói có thể đổi nhãn.", 404)
    label = " ".join(payload.label.split())
    if not label:
        raise AppError("INVALID_LABEL", "Nhãn người nói không được để trống.", 422)
    for row in targets:
        row["speaker_label"] = label
        row.setdefault("data", {})["speaker_label"] = label
    parent = mongo.db.transcript_versions.find_one({"_id": meeting["active_transcript_id"]})
    version = create_version(
        mongo, meeting, rows, reason="Đổi nhãn người nói", run_path=parent.get("run_path")
    )
    try:
        result = repo.update(
            meeting, {"active_transcript_id": version["_id"]}, content_changed=True
        )
    except BaseException:
        discard_version(mongo, version["_id"])
        raise
    mongo.audit(
        user["_id"], "speaker_renamed", meeting_id, label=label, speaker_key=payload.speaker_key
    )
    return public(result)
