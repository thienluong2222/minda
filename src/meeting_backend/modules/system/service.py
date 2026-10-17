"""Lightweight diagnostics and measured experiment records; no model inference here."""

import importlib.util
import platform
import shutil
import subprocess
from datetime import UTC, datetime

from meeting_backend.core.errors import AppError
from meeting_backend.core.settings import ROOT
from meeting_backend.infrastructure.mongodb.client import new_id, now, public
from meeting_backend.modules.meetings.repository import MeetingRepository
from meeting_backend.modules.system.schemas import Preset


def preset(mongo):
    record = mongo.db.settings.find_one({"_id": "processing_preset"})
    return {
        key: value
        for key, value in (record or Preset().model_dump()).items()
        if key not in {"_id", "updated_by", "created_at", "updated_at"}
    }


def capabilities(mongo):
    # model_runtime only reads settings/cache; it does not import Torch/MLX or load weights.
    from meeting_pipeline.minutes.model_runtime import model_status

    status = model_status()
    status.pop("busy", None)
    tess = shutil.which("tesseract")
    languages = []
    if tess:
        result = subprocess.run([tess, "--list-langs"], capture_output=True, text=True, timeout=10)
        languages = result.stdout.splitlines()[1:]
    extra = ROOT / "data/ocr_cache"
    if (extra / "vie.traineddata").is_file():
        languages.append("vie")
    return {
        "models": status,
        "preset": preset(mongo),
        "max_sources": mongo.settings.max_sources,
        "max_upload_bytes": mongo.settings.max_upload_bytes,
        "documents": {
            "word": True,
            "pdf_text": bool(importlib.util.find_spec("pypdf")),
            "ocr": bool(tess and "vie" in languages),
            "ocr_languages": sorted(set(languages)),
            "preview": bool(shutil.which("soffice") and shutil.which("pdftoppm")),
        },
        "runtime": {"python": platform.python_version(), "platform": platform.system()},
        "worker": worker_status(mongo),
    }


def worker_status(mongo):
    record = mongo.db.settings.find_one({"_id": "worker_heartbeat"}) or {}
    seen = record.get("last_seen")
    online = bool(seen and (datetime.now(UTC) - datetime.fromisoformat(seen)).total_seconds() < 30)
    return {"online": online, "last_seen": seen, "active_job": record.get("active_job")}


def evaluate(mongo, user, payload):
    import re
    import unicodedata

    import jiwer

    meeting = MeetingRepository(mongo).owned(payload.meeting_id, user)
    version_id = payload.transcript_version_id or meeting.get("active_transcript_id")
    version = mongo.db.transcript_versions.find_one(
        {"_id": version_id, "meeting_id": meeting["_id"]}
    )
    if not version:
        raise AppError("NO_TRANSCRIPT", "Chưa có transcript để đánh giá.", 422)
    rows = list(mongo.db.transcript_segments.find({"version_id": version_id}).sort("index", 1))
    hypothesis = " ".join(r.get("text", "") for r in rows)

    def normalize(text):
        return " ".join(
            re.sub(r"[^\w\s]", "", unicodedata.normalize("NFC", text).casefold()).split()
        )

    reference, output = normalize(payload.reference_text), normalize(hypothesis)
    if not reference:
        raise AppError("EMPTY_REFERENCE", "Tham chiếu không có từ hợp lệ.", 422)
    score = jiwer.process_words(reference, output)
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=5
    ).stdout.strip()
    record = {
        "_id": new_id(),
        "owner_id": user["_id"],
        "meeting_id": meeting["_id"],
        "transcript_version_id": version_id,
        "name": payload.name,
        "created_at": now(),
        "reference_text": payload.reference_text,
        "hypothesis": hypothesis,
        "notes": payload.hypothesis_notes,
        "metrics": {
            "wer": score.wer,
            "cer": jiwer.cer(reference, output),
            "substitutions": score.substitutions,
            "deletions": score.deletions,
            "insertions": score.insertions,
            "reference_words": len(reference.split()),
        },
        "git_revision": revision,
        "normalization": "NFC_lowercase_no_punctuation_v1",
        "speaker_metrics": None,
        "ground_truth_source": "user_supplied",
    }
    mongo.db.experiments.insert_one(record)
    mongo.audit(user["_id"], "experiment_recorded", record["_id"], meeting_id=meeting["_id"])
    return public(record)
