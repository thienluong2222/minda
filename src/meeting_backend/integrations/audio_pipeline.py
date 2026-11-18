"""Heavy audio imports live here and are invoked only by the worker."""

import json
from pathlib import Path

from meeting_backend.core.errors import AppError
from meeting_backend.modules.meetings import timeline as timeline_service
from meeting_backend.modules.transcripts.service import create_version


def configuration(context, *, voice_owner=None):
    from meeting_pipeline.config import load_config

    config = load_config(context.mongo.settings.pipeline_config).model_copy(deep=True)
    config.paths.model_cache_dir = context.mongo.settings.model_cache_dir.resolve()
    config.paths.data_dir = (
        context.root / "pipeline" if voice_owner is None else context.root / "voices" / voice_owner
    )
    config.paths.database_path = config.paths.data_dir / "legacy.sqlite"
    preset = context.job.get("preset_snapshot", {})
    config.identity["method"] = preset.get("identity_method", "prototype_cosine")
    config.asr.fusion_mode = preset.get("asr_fusion_mode", "transcript")
    selected = config.asr.model_variants.get(preset.get("asr_variant", "medium"))
    if selected:
        config.asr.model_id = selected.model_id
        config.asr.model_revision = selected.model_revision
    return config


def normalize_segments(context, run_dir, raw_rows):
    from meeting_pipeline.domain.speaker_identity import person_identity_key

    rows = []
    for index, data in enumerate(raw_rows):
        count = int(data.get("speaker_count") or 1)
        label = data.get("speaker_label") or "Chưa xác định"
        key = person_identity_key(
            label,
            data.get("speaker_id"),
            data.get("meeting_speaker_id"),
            data.get("speaker_status", ""),
            count,
            data.get("overlap_group_id"),
        )
        clip = data.get("evidence_clip_artifact_id") or data.get("processed_clip_artifact_id")
        clip_view = None
        if clip:
            candidate = Path(clip)
            if not candidate.is_absolute():
                candidate = run_dir / candidate
            if candidate.is_file() and candidate.resolve().is_relative_to(context.store.root):
                clip_view = context.artifact(candidate)
        rows.append(
            {
                "turn_id": data.get("turn_id") or f"seg_{index:04d}",
                "text": data.get("text", ""),
                "start_sec": float(data.get("start_sec", 0)),
                "end_sec": float(data.get("end_sec", 0)),
                "speaker_label": label,
                "speaker_key": ":".join(key) if key else None,
                "speaker_count": count,
                "speaker_status": data.get("speaker_status", "unknown"),
                "meeting_speaker_id": data.get("meeting_speaker_id"),
                "needs_review": bool(data.get("needs_review") or count > 1 or not data.get("text")),
                "asr_status": data.get("asr_status", "not_run"),
                "user_edited": bool(data.get("user_edited")),
                "clip": clip_view,
                "clock_id": data.get("clock_id", "meeting"),
                "clock_label": data.get("clock_label", "Cuộc họp"),
                "time_status": data.get("time_status", "meeting"),
                "meeting_start_sec": data.get("meeting_start_sec", data.get("start_sec")),
                "meeting_end_sec": data.get("meeting_end_sec", data.get("end_sec")),
                "recording_evidence": data.get("recording_evidence", []),
                "excluded_from_minutes": bool(data.get("excluded_from_minutes")),
                "data": data,
            }
        )
    return rows


def transcribe(context):
    context.stage("Kiểm tra nguồn âm thanh và hồ sơ người tham gia")
    meeting = context.resource()
    assets = timeline_service.assets_for(context.mongo, meeting)
    plan = timeline_service.processing_input(meeting, assets, context.mongo.settings)
    expected_hash = context.job.get("payload", {}).get("input_timeline_hash")
    if expected_hash and expected_hash != plan["timeline_hash"]:
        raise AppError("INPUT_CHANGED", "Bố cục nguồn đã thay đổi sau khi tạo tác vụ.", 409)
    sources = [assets[source_id] for source_id in plan["source_ids"]]
    from meeting_pipeline.application.speakers import SpeakerRegistry
    from meeting_pipeline.pipeline.multi_source_fusion import MultiSourceFusionPipeline

    if not sources:
        raise AppError("NO_SOURCES", "Cuộc họp chưa có nguồn âm thanh.", 422)
    paths = []
    for source in sources:
        artifact = context.mongo.db.artifacts.find_one(
            {
                "_id": source["artifact_id"],
                "owner_id": meeting["owner_id"],
            }
        )
        if not artifact:
            raise AppError("NOT_FOUND", "Có file âm thanh không còn tồn tại.", 422)
        paths.append(context.store.resolve(artifact))
    profiles = []
    participant_ids = meeting.get("participant_ids", [])
    if participant_ids:
        registry = SpeakerRegistry(configuration(context, voice_owner=meeting["owner_id"]))
        records = list(
            context.mongo.db.speakers.find(
                {
                    "_id": {"$in": participant_ids},
                    "owner_id": meeting["owner_id"],
                    "state": "ready",
                    "trashed": False,
                }
            )
        )
        if len(records) != len(participant_ids):
            raise AppError("INVALID_PARTICIPANT", "Hồ sơ người tham gia đã thay đổi.", 422)
        profiles = registry.load([r["core_speaker_id"] for r in records])
    context.stage("Đồng bộ, chép lời, dung hợp và nhận diện người nói")
    config = configuration(context)
    method = context.job.get("preset_snapshot", {}).get(
        "fusion_method", "F5_RULE_WEIGHTED_CORRECTED"
    )
    if plan["mode"] == "timeline":
        from meeting_pipeline.pipeline.timeline_audio import TimelineAudioPipeline

        run = TimelineAudioPipeline(config).run(
            meeting["title"],
            dict(zip(plan["source_ids"], paths, strict=True)),
            plan["timeline"],
            profiles,
            fusion_method=method,
            check=context.check,
            timeline_hash=plan["timeline_hash"],
        )
    else:
        run = MultiSourceFusionPipeline(config).run(
            meeting["title"],
            paths,
            profiles,
            fusion_method=method,
        )
    context.check()
    context.stage("Lưu transcript, bằng chứng và các file đối chiếu")
    (run / "input_timeline.json").write_text(
        json.dumps(
            {
                "timeline_hash": plan["timeline_hash"],
                "timeline": plan["timeline"],
                "processing_mode": plan["mode"],
                "source_assets": {
                    (f"source-{index}" if plan["mode"] == "legacy_auto" else source["_id"]): source[
                        "_id"
                    ]
                    for index, source in enumerate(sources, start=1)
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    timeline = json.loads((run / "timeline.json").read_text())
    raw_rows = timeline.get("segments", [])
    manifest = json.loads((run / "manifest.json").read_text())
    version = create_version(
        context.mongo,
        meeting,
        normalize_segments(context, run, raw_rows),
        reason="Xử lý âm thanh",
        run_path=str(run),
        input_timeline_hash=plan["timeline_hash"],
        timing_complete=manifest.get("timing_complete", True),
    )
    exports = []
    for file in sorted((run / "exports").glob("*")):
        if file.is_file():
            exports.append(context.artifact(file))
    duration = max(
        (float(s.get("duration_sec") or 0) for s in manifest.get("sources", [])), default=0
    )
    if not duration:
        duration = max((r.get("end_sec", 0) for r in raw_rows), default=0)
    sync_path = run / "sync_metadata.json"
    if sync_path.is_file():
        sync = json.loads(sync_path.read_text()).get("sources", {})
        duration = max(
            (
                float(meta["valid_coverage_interval"][1])
                for meta in sync.values()
                if meta.get("status") != "alignment_failed" and meta.get("valid_coverage_interval")
            ),
            default=duration,
        )
    if "timing_complete" in manifest:
        duration = manifest.get("duration_sec")
    alignment = None
    if (run / "alignment.json").is_file():
        alignment = context.artifact(run / "alignment.json")
    context.publish(
        {
            "active_transcript_id": version["_id"],
            "state": "transcript_ready",
            "transcript_stale": False,
            "minutes_stale": bool(meeting.get("active_minutes_id")),
            "duration_sec": duration,
            "transcript_exports": exports,
            "last_models": manifest.get("models", {}),
            "processing_summary": {
                "segments": len(raw_rows),
                "sources": len(sources),
                "timings": manifest.get("timings", {}),
                "timing_complete": manifest.get("timing_complete", True),
                "component_count": manifest.get("component_count", 1),
                "asr_fusion_mode": config.asr.fusion_mode,
                "asr_input_stats": manifest.get("asr_input_stats", {}),
                "alignment": alignment,
                "input_timeline_hash": plan["timeline_hash"],
            },
        },
        content_changed=True,
        result={"transcript_version_id": version["_id"], "run_id": run.name},
    )


def enroll_voice(context):
    from meeting_pipeline.application.speakers import SpeakerRegistry

    context.stage("Kiểm tra mẫu giọng và tạo embedding")
    speaker = context.resource()
    sample_ids = context.job.get("payload", {}).get("sample_ids", speaker.get("sample_ids", []))
    artifacts = list(
        context.mongo.db.artifacts.find(
            {"_id": {"$in": sample_ids}, "owner_id": speaker["owner_id"]}
        )
    )
    if len(artifacts) != len(sample_ids):
        raise AppError("INVALID_SAMPLES", "Có mẫu giọng không còn tồn tại.", 422)
    registry = SpeakerRegistry(configuration(context, voice_owner=speaker["owner_id"]))
    profile = registry.enroll(speaker["name"], [context.store.resolve(a) for a in artifacts])
    context.publish(
        {
            "state": "ready",
            "sample_ids": sample_ids,
            "metadata": profile,
            "core_speaker_id": profile["speaker_id"],
        },
        result={"sample_count": profile["sample_count"]},
    )
