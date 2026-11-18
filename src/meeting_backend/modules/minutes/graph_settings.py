"""Server-enforced graph policy, immutable inputs and owner-scoped style feedback."""

from __future__ import annotations

import re
from typing import Any

from meeting_backend.infrastructure.mongodb.client import now
from meeting_pipeline.minutes.graph_contracts import StyleProfile, default_style, digest
from meeting_pipeline.minutes.style_memory import learn_style_rules, preserves_reviewed_claims


def freeze_inputs(mongo, resource, user, job_id, payload, preset):
    from meeting_backend.core.errors import AppError
    from meeting_backend.modules.transcripts.service import rows_for

    options = dict(payload.get("options", {}))
    graph_enabled = bool(preset.get("minutes_graph_enabled", True))
    options["graph_enabled"] = graph_enabled
    if graph_enabled:
        options.update(use_model=True, use_fcm=True)
    profile_record = mongo.db.style_profiles.find_one({"_id": user["_id"], "owner_id": user["_id"]})
    profile = (
        StyleProfile.model_validate(profile_record["profile"])
        if profile_record
        else default_style()
    )
    metadata = {
        "meeting_id": resource["_id"],
        "meeting_name": resource["title"],
        "meeting_date": resource.get("date", ""),
        "location": resource.get("location", ""),
        "agenda": payload.get("agenda", []),
        "style_profile": profile.model_dump(),
        "transcript_version_id": resource.get("active_transcript_id"),
        "input_content_revision": resource.get("content_revision", 0),
        "preset_revision": preset.get("revision", 1),
    }
    rows = rows_for(mongo, resource["active_transcript_id"])
    aliases = {row["_id"]: row.get("data", {}).get("turn_id") or row["_id"] for row in rows}
    aliases.update({value: value for value in list(aliases.values())})
    requested_sessions = payload.get("turn_sessions", {})
    if set(requested_sessions) - set(aliases) or any(
        not value.strip() or len(value) > 120 for value in requested_sessions.values()
    ):
        raise AppError(
            "INVALID_SESSION_MAP", "Phân phiên chứa lượt lời hoặc nhãn không hợp lệ.", 422
        )
    metadata["turn_sessions"] = {
        aliases[key]: value.strip() for key, value in requested_sessions.items()
    }
    records = [
        {
            "_id": f"{job_id}:{i}",
            "snapshot_id": job_id,
            "owner_id": user["_id"],
            "meeting_id": resource["_id"],
            "index": i,
            "segment": row,
        }
        for i, row in enumerate(rows)
    ]
    # Segments are separate documents: long meetings do not form one giant BSON payload.
    if records:
        mongo.db.minutes_input_segments.insert_many(records)
    mongo.db.minutes_input_snapshots.insert_one(
        {
            "_id": job_id,
            "owner_id": user["_id"],
            "meeting_id": resource["_id"],
            "metadata": metadata,
            "source_sha256": digest(rows),
            "row_count": len(rows),
            "created_at": now(),
        }
    )
    return {
        **payload,
        "options": options,
        "input_snapshot_id": job_id,
        "transcript_version_id": resource["active_transcript_id"],
        "metadata_snapshot": metadata,
    }


def learn_reviewed_style(mongo, user, meeting_id, version_id) -> dict[str, Any]:
    import json
    from pathlib import Path

    from meeting_backend.modules.system.service import preset

    if not preset(mongo).get("minutes_style_learning_enabled", True):
        return {"status": "disabled"}
    version = mongo.db.minutes_versions.find_one(
        {"_id": version_id, "owner_id": user["_id"], "meeting_id": meeting_id}
    )
    if not version or version.get("reason") != "edit_facts" or not version.get("parent_id"):
        return {"status": "no_confirmed_edit_pair"}
    parent = mongo.db.minutes_versions.find_one(
        {"_id": version["parent_id"], "owner_id": user["_id"], "meeting_id": meeting_id}
    )
    if not parent or parent.get("input_content_revision") != version.get("input_content_revision"):
        return {"status": "different_source"}
    run = Path(parent.get("run_path", "")).resolve()
    plan_path = run / "minutes/content_plan.json"
    if not run.is_relative_to(mongo.settings.data_dir.resolve()) or not plan_path.is_file():
        return {"status": "no_claim_alignments"}
    plan = json.loads(plan_path.read_text())
    before = {f["field_id"]: f for f in parent.get("facts", [])}
    names = {
        re.split(r"\s+[\u2014\u2013]\s+", unit.get("speaker", ""), maxsplit=1)[0]
        for unit in (version.get("topics") or {}).get("units", [])
    }
    names = {
        name
        for name in names
        if name and not name.casefold().startswith(("speaker", "người", "chưa"))
    }
    narrative_ids = {
        f["field_id"]
        for f in version.get("schema", {}).get("fields", [])
        if f.get("semantic_type")
        in {"discussion_summary", "meeting_agenda", "meeting_agenda_summary"}
    }
    edits = []
    for fact in version.get("facts", []):
        old = before.get(fact["field_id"], {})
        a, b = old.get("value"), fact.get("value")
        if (
            fact["field_id"] not in narrative_ids
            or not isinstance(a, str)
            or not isinstance(b, str)
            or a == b
        ):
            continue
        edits.append(
            {
                "edit_id": version_id + ":" + fact["field_id"],
                "before": a,
                "after": b,
                "approved": True,
                "facts_unchanged": preserves_reviewed_claims(a, b, plan),
                "names": sorted(names),
            }
        )
    audit_id = digest([user["_id"], version_id])
    for _ in range(3):
        record = mongo.db.style_profiles.find_one({"_id": user["_id"]})
        profile = StyleProfile.model_validate(record["profile"]) if record else default_style()
        profile.profile_id = "owner_" + user["_id"]
        profile.provenance = "confirmed_owner_edit_signals"
        updated, audit = learn_style_rules(profile, edits)
        if updated == profile:
            break
        revision = record.get("revision", 0) if record else 0
        query = (
            {"_id": user["_id"], "revision": revision}
            if record
            else {"_id": user["_id"], "revision": {"$exists": False}}
        )
        from pymongo.errors import DuplicateKeyError

        try:
            result = mongo.db.style_profiles.update_one(
                query,
                {
                    "$set": {
                        "owner_id": user["_id"],
                        "profile": updated.model_dump(),
                        "revision": revision + 1,
                        "updated_at": now(),
                    }
                },
                upsert=record is None,
            )
        except DuplicateKeyError:
            continue
        if result.modified_count or result.upserted_id:
            break
    else:
        return {"status": "concurrent_update_deferred"}
    mongo.db.style_learning_audit.update_one(
        {"_id": audit_id},
        {
            "$setOnInsert": {
                "owner_id": user["_id"],
                "meeting_id": meeting_id,
                "minutes_version_id": version_id,
                "audit": audit,
                "created_at": now(),
            }
        },
        upsert=True,
    )
    return {"status": "processed", **audit}
