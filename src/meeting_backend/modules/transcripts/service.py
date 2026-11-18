"""Immutable transcript revisions, evidence-preserving edits and speaker renames."""

from copy import deepcopy
from math import isfinite

from meeting_backend.core.errors import AppError
from meeting_backend.infrastructure.artifacts.store import ArtifactStore
from meeting_backend.infrastructure.mongodb.client import new_id, now, public
from meeting_backend.modules.meetings.repository import MeetingRepository


def rows_for(mongo, version_id):
    return list(mongo.db.transcript_segments.find({"version_id": version_id}).sort("index", 1))


def create_version(
    mongo, meeting, rows, *, reason, run_path=None, input_timeline_hash=None, timing_complete=None
):
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
        "timing_complete": (
            all(row.get("data", row).get("timing_complete", True) for row in rows)
            if timing_complete is None
            else timing_complete
        ),
    }
    if input_timeline_hash is not None:
        version["input_timeline_hash"] = input_timeline_hash
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
    result = {key: value for key, value in public(row).items() if key not in {"data"}}
    data = row.get("data") or {}
    issues = set(data.get("warnings") or [])
    for source in data.get("source_evidence") or []:
        issues.update(source.get("asr_warnings") or [])
    if "asr_single_source_unverified" in issues:
        issues.discard("unverified_fusion_consensus")
    if "asr_unverified_short_fragment" in issues:
        issues.difference_update(
            {
                "asr_short_context",
                "asr_single_source_unverified",
                "asr_retry_succeeded",
            }
        )
    if "asr_short_context" in issues:
        issues.discard("empty_fused_transcript")
    descriptions = (
        (
            {"asr_unverified_short_fragment"},
            "Đoạn quá ngắn, các nguồn chưa xác nhận được lời chép.",
        ),
        ({"asr_short_context"}, "Đoạn âm thanh ngắn, cần nghe lại trong ngữ cảnh."),
        ({"unverified_fusion_consensus"}, "Các nguồn ghi có lời nhận dạng khác nhau."),
        ({"asr_single_source_unverified"}, "Lời chép mới có một nguồn ghi để đối chiếu."),
        ({"empty_fused_transcript"}, "Chưa nhận dạng được lời chép hợp lệ."),
        (
            {"asr_invalid_word_timestamp", "asr_word_time_uncertain"},
            "Một số từ có mốc thời gian chưa chắc chắn.",
        ),
        ({"asr_retry_succeeded"}, "Đoạn này đã phải nhận dạng lại."),
    )
    result["review_reasons"] = [text for codes, text in descriptions if issues & codes][:3]
    candidates, seen = [], {row.get("text", "").strip()}
    for source in data.get("source_evidence") or []:
        text = (source.get("candidate_scores", {}).get("transcript") or "").strip()
        if source.get("asr_status") != "transcribed" or not text or text in seen:
            continue
        seen.add(text)
        identifier = str(source.get("source_id", ""))
        number = identifier.removeprefix("source-")
        candidates.append(
            {
                "label": "Nguồn ghi " + number if number.isdigit() else "Bản nhận dạng khác",
                "text": text,
            }
        )
    result["source_candidates"] = candidates
    return result


def review_context(mongo, meeting, row):
    """Expose bounded original-file context for short, uncertain utterances."""
    try:
        duration = float(row["end_sec"]) - float(row["start_sec"])
    except (KeyError, TypeError, ValueError):
        return None
    if not row.get("needs_review") or not 0 < duration < 1:
        return None
    evidence = (row.get("data") or {}).get("selected_recording_evidence") or []
    if not evidence:
        return None
    reference = evidence[0]
    source = mongo.db.sources.find_one(
        {
            "_id": reference.get("asset_id"),
            "meeting_id": meeting["_id"],
            "owner_id": meeting["owner_id"],
        }
    )
    part = next(
        (
            clip
            for clip in (meeting.get("timeline") or {}).get("clips", [])
            if clip["id"] == reference.get("clip_id")
            and clip["asset_id"] == reference.get("asset_id")
        ),
        None,
    )
    if not source or not part:
        return None
    artifact = mongo.db.artifacts.find_one(
        {
            "_id": source["artifact_id"],
            "owner_id": meeting["owner_id"],
            "resource_id": meeting["_id"],
        }
    )
    if not artifact:
        return None
    try:
        core_start, core_end = (
            float(reference[key]) for key in ("source_start_sec", "source_end_sec")
        )
        lower = part["source_in_ms"] / 1000
        upper = part["source_out_ms"] / 1000
    except (KeyError, TypeError, ValueError):
        return None
    if not all(isfinite(value) for value in (core_start, core_end, lower, upper)):
        return None
    if not lower - 1e-4 <= core_start < core_end <= upper + 1e-4:
        return None
    store = ArtifactStore(mongo)
    try:
        store.resolve(artifact)
    except AppError:
        return None
    return {
        "audio": store.view(artifact),
        "start_sec": max(lower, core_start - 2),
        "end_sec": min(upper, core_end + 2),
    }


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
    parent = mongo.db.transcript_versions.find_one({"_id": meeting["active_transcript_id"]})
    version = create_version(
        mongo,
        meeting,
        rows,
        reason="Sửa transcript",
        run_path=parent.get("run_path"),
        input_timeline_hash=parent.get("input_timeline_hash"),
        timing_complete=parent.get("timing_complete", True),
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
        mongo,
        meeting,
        rows,
        reason="Đổi nhãn người nói",
        run_path=parent.get("run_path"),
        input_timeline_hash=parent.get("input_timeline_hash"),
        timing_complete=parent.get("timing_complete", True),
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
