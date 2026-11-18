"""Real MongoDB integration tests, isolated database and artifact root per test."""

from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from meeting_backend.core.settings import Settings
from meeting_backend.main import create_app
from meeting_backend.modules.transcripts.service import create_version, rows_for
from meeting_backend.worker.runner import Runner

PASSWORD = "test-password-12345"


def wav_bytes():
    import wave

    stream = BytesIO()
    with wave.open(stream, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\0" * 32000)
    return stream.getvalue()


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        mongo_database="meeting_app_test_" + uuid4().hex,
        data_dir=tmp_path,
        web_dist=tmp_path / "no-web",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        client.post(
            "/api/v1/auth/setup",
            json={"username": "admin", "password": PASSWORD, "display_name": "Admin"},
        ).raise_for_status()
        login(client, "admin")
        yield client
        app.state.mongo.client.drop_database(settings.mongo_database)


def login(client, username):
    client.post(
        "/api/v1/auth/login", json={"username": username, "password": PASSWORD}
    ).raise_for_status()
    client.headers["X-CSRF-Token"] = client.cookies.get("meeting_csrf")


def meeting(client):
    response = client.post("/api/v1/meetings", json={"title": "Họp tiến độ"})
    response.raise_for_status()
    return response.json()


@pytest.mark.parametrize("pending_kind", ["previous_edit", "conflicting"])
def test_minutes_review_requires_reconciling_previous_edit(client, pending_kind):
    m = meeting(client)
    db = client.app.state.mongo.db
    version_id = uuid4().hex
    db.meetings.update_one({"_id": m["id"]}, {"$set": {"active_minutes_id": version_id}})
    db.minutes_versions.insert_one(
        {
            "_id": version_id,
            "facts": [
                {"field_id": "plain", "previous_edit": None},
                {
                    "field_id": "end_time",
                    "previous_edit": (
                        {"value": "10", "minutes_version_id": "old"}
                        if pending_kind == "previous_edit"
                        else None
                    ),
                    "status": "conflicting" if pending_kind == "conflicting" else "needs_review",
                },
                {"field_id": "legacy"},
            ],
        }
    )
    url = f"/api/v1/meetings/{m['id']}/minutes/review"
    response = client.post(url, json={"revision": m["revision"]})
    assert response.status_code == 409
    db.minutes_versions.update_one(
        {"_id": version_id},
        {"$set": {"facts.1.previous_edit": None, "facts.1.status": "supported"}},
    )
    response = client.post(url, json={"revision": m["revision"]})
    response.raise_for_status()
    assert response.json()["reviewed_version"] == version_id


def test_meeting_status_filters_before_pagination_and_scopes_ownership(client):
    m = meeting(client)
    collection = client.app.state.mongo.db.meetings
    base = collection.find_one({"_id": m["id"]})
    for index in range(35):
        item = {**base, "_id": uuid4().hex, "title": f"Kế hoạch {index}"}
        item.update(
            state="transcript_ready",
            updated_at=(
                datetime.fromisoformat(base["updated_at"]) + timedelta(seconds=index + 1)
            ).isoformat(),
        )
        collection.insert_one(item)
    # The matching draft is older than an entire page of other states.
    result = client.get("/api/v1/meetings", params={"status": "draft", "limit": 30}).json()
    assert result["total"] == 1
    assert [item["id"] for item in result["items"]] == [m["id"]]
    result = client.get(
        "/api/v1/meetings", params={"status": "transcript_ready", "page": 2, "limit": 30}
    ).json()
    assert result["total"] == 35 and len(result["items"]) == 5
    collection.insert_one({**base, "_id": uuid4().hex, "owner_id": "another-owner"})
    collection.insert_one({**base, "_id": uuid4().hex, "trashed": True})
    assert client.get("/api/v1/meetings", params={"status": "draft"}).json()["total"] == 1
    collection.update_one({"_id": m["id"]}, {"$set": {"active_job": "queued-job"}})
    assert client.get("/api/v1/meetings", params={"status": "draft"}).json()["total"] == 0
    assert client.get("/api/v1/meetings", params={"status": "processing"}).json()["total"] == 1
    assert client.get("/api/v1/meetings", params={"status": "unrecognized"}).status_code == 422


def test_needs_review_filter_matches_missing_changed_and_stale_review_versions(client):
    m = meeting(client)
    collection = client.app.state.mongo.db.meetings
    base = collection.find_one({"_id": m["id"]})
    expected = set()
    cases = [
        {"active_minutes_id": "v1"},
        {"active_minutes_id": "v2", "reviewed_version": "v1"},
        {"active_minutes_id": "v2", "reviewed_version": "v2", "minutes_stale": True},
        {"active_minutes_id": "v2", "reviewed_version": "v2"},
        {"active_minutes_id": None},
    ]
    for index, changes in enumerate(cases):
        item = {**base, "_id": uuid4().hex, "state": "minutes_ready", **changes}
        collection.insert_one(item)
        if index < 3:
            expected.add(item["_id"])
    result = client.get("/api/v1/meetings", params={"status": "needs_review"}).json()
    assert result["total"] == 3
    assert {item["id"] for item in result["items"]} == expected


def test_capabilities_expose_timeline_limits_and_two_hour_audio_duration(client):
    from meeting_pipeline.config import load_config

    settings = client.app.state.settings
    capabilities = client.get("/api/v1/capabilities").json()
    assert capabilities["max_source_files"] == settings.max_source_files
    assert capabilities["max_timeline_clips"] == settings.max_timeline_clips
    assert (
        capabilities["max_audio_duration_sec"]
        == load_config(settings.pipeline_config).audio.max_duration_seconds
        == 7200
    )


def upload_audio(client, m, count=1, **query):
    result = client.post(
        f"/api/v1/meetings/{m['id']}/sources",
        params={"revision": m["revision"], **query},
        files=[("files", (f"clip-{i}.wav", wav_bytes(), "audio/wav")) for i in range(count)],
    )
    result.raise_for_status()
    return result.json()


def read_timeline(client, meeting_id):
    result = client.get(f"/api/v1/meetings/{meeting_id}/timeline")
    result.raise_for_status()
    return result.json()


def edit_timeline(client, meeting_id, view, operations):
    return client.patch(
        f"/api/v1/meetings/{meeting_id}/timeline",
        json={"revision": view["revision"], "operations": operations},
    )


def test_timeline_legacy_read_is_nonmutating_and_cosmetic_edits_keep_content(client):
    m = upload_audio(client, meeting(client))
    first = read_timeline(client, m["id"])
    assert first["legacy"] is True
    assert first["processing"]["supported"] is True
    assert first["timeline"]["clips"][0]["placement"]["gap_before_ms"] is None
    assert "timeline" not in client.app.state.mongo.db.meetings.find_one({"_id": m["id"]})
    track_id = first["timeline"]["tracks"][0]["id"]
    updated = edit_timeline(
        client,
        m["id"],
        first,
        [
            {"op": "update_track", "track_id": track_id, "name": "Điện thoại A"},
        ],
    )
    updated.raise_for_status()
    second = updated.json()
    assert second["content_revision"] == first["content_revision"]
    assert second["timeline_hash"] == first["timeline_hash"]
    assert read_timeline(client, m["id"])["timeline"] == second["timeline"]
    assert (
        edit_timeline(
            client,
            m["id"],
            first,
            [
                {"op": "update_track", "track_id": track_id, "name": "Bản cũ"},
            ],
        ).status_code
        == 409
    )


def test_timeline_move_is_atomic_and_keeps_ids_and_original_files(client):
    import hashlib

    from meeting_backend.infrastructure.artifacts.store import ArtifactStore

    m = upload_audio(client, meeting(client), count=2)
    mongo = client.app.state.mongo
    store = ArtifactStore(mongo)
    paths = [store.resolve(mongo.db.artifacts.find_one({"_id": item})) for item in m["source_ids"]]
    hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
    first = read_timeline(client, m["id"])
    a, b = first["timeline"]["tracks"]
    clip_a, clip_b = a["clip_ids"][0], b["clip_ids"][0]
    updated = edit_timeline(
        client,
        m["id"],
        first,
        [
            {"op": "move_clip", "clip_id": clip_b, "track_id": a["id"], "before_clip_id": clip_a},
        ],
    )
    updated.raise_for_status()
    second = updated.json()
    assert second["timeline"]["tracks"][0]["clip_ids"] == [clip_b, clip_a]
    assert second["timeline"]["tracks"][1]["clip_ids"] == []
    assert {clip["id"] for clip in second["timeline"]["clips"]} == {clip_a, clip_b}
    assert [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths] == hashes
    assert read_timeline(client, m["id"])["timeline"] == second["timeline"]
    assert second["processing"]["supported"] is True
    assert second["processing"]["mode"] == "timeline"
    process = client.post(
        f"/api/v1/meetings/{m['id']}/process", json={"revision": second["revision"]}
    )
    assert process.status_code == 202
    client.post(f"/api/v1/jobs/{process.json()['id']}/cancel").raise_for_status()
    second = read_timeline(client, m["id"])
    # A bad destination must not save the first, otherwise-valid operation.
    rejected = edit_timeline(
        client,
        m["id"],
        second,
        [
            {"op": "update_track", "track_id": a["id"], "name": "Không được lưu"},
            {"op": "move_clip", "clip_id": clip_b, "track_id": "missing-track"},
        ],
    )
    assert rejected.status_code == 422
    assert read_timeline(client, m["id"])["timeline"] == second["timeline"]
    assert read_timeline(client, m["id"])["revision"] == second["revision"]


def test_timeline_known_gap_is_not_transferred_to_a_new_predecessor(client):
    m = upload_audio(client, meeting(client), count=3)
    view = read_timeline(client, m["id"])
    tracks = view["timeline"]["tracks"]
    a, b, c = [track["clip_ids"][0] for track in tracks]
    result = edit_timeline(
        client,
        m["id"],
        view,
        [
            {"op": "set_placement", "clip_id": a, "placement": {"kind": "anchored", "start_ms": 0}},
            {
                "op": "move_clip",
                "clip_id": b,
                "track_id": tracks[0]["id"],
                "placement": {"kind": "sequential", "gap_before_ms": 1000},
            },
            {
                "op": "move_clip",
                "clip_id": c,
                "track_id": tracks[0]["id"],
                "placement": {"kind": "sequential", "gap_before_ms": 2000},
            },
        ],
    )
    result.raise_for_status()
    known = result.json()
    assert known["resolved_positions"][b]["start_ms"] == 2000
    assert known["resolved_positions"][c]["start_ms"] == 5000
    moved = edit_timeline(
        client,
        m["id"],
        known,
        [
            {"op": "move_clip", "clip_id": b, "track_id": tracks[0]["id"]},
        ],
    )
    moved.raise_for_status()
    after = moved.json()
    assert after["timeline"]["tracks"][0]["clip_ids"] == [a, c, b]
    clips = {item["id"]: item for item in after["timeline"]["clips"]}
    assert clips[b]["placement"]["gap_before_ms"] is None
    assert clips[c]["placement"]["gap_before_ms"] is None
    assert clips[b]["timing_history"][-1]["placement"]["after_clip_id"] == a
    assert clips[c]["timing_history"][-1]["placement"]["after_clip_id"] == b
    assert after["resolved_positions"][c]["start_ms"] is None


def test_timeline_upload_pool_and_many_files_on_one_source(client):
    m = meeting(client)
    pooled = upload_audio(client, m, count=9, timeline_mode="true")
    view = read_timeline(client, m["id"])
    assert len(view["timeline"]["unassigned_asset_ids"]) == 9
    assert not view["timeline"]["tracks"]
    assert not view["processing"]["supported"]
    result = edit_timeline(
        client,
        m["id"],
        view,
        [
            {"op": "create_track", "id": "phone-a", "name": "Điện thoại A"},
            *[
                {"op": "add_clip", "id": f"part-{i}", "asset_id": asset_id, "track_id": "phone-a"}
                for i, asset_id in enumerate(pooled["source_ids"])
            ],
        ],
    )
    result.raise_for_status()
    placed = result.json()
    assert len(placed["timeline"]["tracks"]) == 1
    assert len(placed["timeline"]["tracks"][0]["clip_ids"]) == 9
    assert placed["timeline"]["unassigned_asset_ids"] == []
    m["revision"] = placed["revision"]
    upload_audio(client, m, track_id="phone-a")
    latest = read_timeline(client, m["id"])
    assert len(latest["timeline"]["tracks"][0]["clip_ids"]) == 10
    assert all(clip["placement"]["gap_before_ms"] is None for clip in latest["timeline"]["clips"])


def test_timeline_invalid_ranges_positions_and_false_verification_are_rejected(client):
    m = upload_audio(client, meeting(client), count=2)
    view = read_timeline(client, m["id"])
    a, b = view["timeline"]["tracks"]
    clip = a["clip_ids"][0]
    cases = [
        [{"op": "set_range", "clip_id": clip, "source_in_ms": 100, "source_out_ms": 100}],
        [{"op": "set_range", "clip_id": clip, "source_in_ms": 0, "source_out_ms": 1001}],
        [
            {
                "op": "set_placement",
                "clip_id": clip,
                "placement": {
                    "kind": "anchored",
                    "start_ms": 0,
                    "origin": "audio_match",
                    "status": "verified",
                },
            }
        ],
        [
            {
                "op": "set_placement",
                "clip_id": clip,
                "placement": {"kind": "anchored", "start_ms": 0},
            },
            {
                "op": "move_clip",
                "clip_id": b["clip_ids"][0],
                "track_id": a["id"],
                "placement": {"kind": "anchored", "start_ms": 500},
            },
        ],
    ]
    for operations in cases:
        result = edit_timeline(client, m["id"], view, operations)
        assert result.status_code == 422, result.text
        assert read_timeline(client, m["id"])["revision"] == view["revision"]


def test_timeline_content_change_marks_results_stale_and_snapshots_legacy_jobs(client):
    m = upload_audio(client, meeting(client))
    view = read_timeline(client, m["id"])
    response = client.post(
        f"/api/v1/meetings/{m['id']}/process", json={"revision": view["revision"]}
    )
    response.raise_for_status()
    job_id = response.json()["id"]
    job = client.app.state.mongo.db.jobs.find_one({"_id": job_id})
    assert job["payload"]["input_timeline_hash"] == view["timeline_hash"]
    assert job["payload"]["source_ids"] == m["source_ids"]
    busy = read_timeline(client, m["id"])
    assert (
        edit_timeline(
            client,
            m["id"],
            busy,
            [
                {
                    "op": "set_placement",
                    "clip_id": view["timeline"]["clips"][0]["id"],
                    "placement": {"kind": "anchored", "start_ms": 1000},
                },
            ],
        ).status_code
        == 409
    )
    client.post(f"/api/v1/jobs/{job_id}/cancel").raise_for_status()
    client.app.state.mongo.db.meetings.update_one(
        {"_id": m["id"]},
        {
            "$set": {
                "active_transcript_id": "old-transcript",
                "active_minutes_id": "old-minutes",
                "state": "minutes_ready",
            }
        },
    )
    view = read_timeline(client, m["id"])
    result = edit_timeline(
        client,
        m["id"],
        view,
        [
            {
                "op": "set_placement",
                "clip_id": view["timeline"]["clips"][0]["id"],
                "placement": {"kind": "anchored", "start_ms": 1000},
            },
        ],
    )
    result.raise_for_status()
    saved = client.get(f"/api/v1/meetings/{m['id']}").json()
    assert saved["transcript_stale"] is True and saved["minutes_stale"] is True
    assert saved["state"] == "draft"
    assert saved["content_revision"] == view["content_revision"] + 1


def test_admin_asr_fusion_mode_is_snapshotted_for_new_jobs(client):
    from types import SimpleNamespace

    from meeting_backend.integrations.audio_pipeline import configuration

    mongo = client.app.state.mongo
    initial = client.get("/api/v1/admin/preset").json()
    assert initial["asr_fusion_mode"] == "transcript"

    def queue_transcription():
        m = upload_audio(client, meeting(client))
        revision = read_timeline(client, m["id"])["revision"]
        response = client.post(f"/api/v1/meetings/{m['id']}/process", json={"revision": revision})
        response.raise_for_status()
        return mongo.db.jobs.find_one({"_id": response.json()["id"]})

    original_job = queue_transcription()
    saved = client.put("/api/v1/admin/preset", json={**initial, "asr_fusion_mode": "audio"})
    saved.raise_for_status()
    assert saved.json()["asr_fusion_mode"] == "audio"
    new_job = queue_transcription()
    for job, expected in ((original_job, "transcript"), (new_job, "audio")):
        job = mongo.db.jobs.find_one({"_id": job["_id"]})
        context = SimpleNamespace(mongo=mongo, job=job, root=mongo.settings.data_dir)
        assert job["preset_snapshot"]["asr_fusion_mode"] == expected
        assert configuration(context).asr.fusion_mode == expected


def test_timeline_permissions_and_foreign_asset_references(client):
    m = upload_audio(client, meeting(client))
    other = upload_audio(client, meeting(client))
    view = read_timeline(client, m["id"])
    invalid = edit_timeline(
        client,
        m["id"],
        view,
        [
            {
                "op": "add_clip",
                "id": "foreign-clip",
                "track_id": view["timeline"]["tracks"][0]["id"],
                "asset_id": other["source_ids"][0],
            },
        ],
    )
    assert invalid.status_code == 422
    client.post(
        "/api/v1/admin/users",
        json={
            "username": "member",
            "password": PASSWORD,
            "display_name": "Member",
        },
    ).raise_for_status()
    login(client, "member")
    assert client.get(f"/api/v1/meetings/{m['id']}/timeline").status_code == 404
    assert (
        edit_timeline(
            client,
            m["id"],
            view,
            [
                {"op": "create_track", "id": "unauthorized", "name": "X"},
            ],
        ).status_code
        == 404
    )


def test_audio_upload_checks_pipeline_duration_limit_and_rolls_back(client, tmp_path):
    from pathlib import Path

    import yaml

    config = yaml.safe_load(Path("configs/default.yaml").read_text())
    config["audio"]["max_duration_seconds"] = 0.5
    path = tmp_path / "short-limit.yaml"
    path.write_text(yaml.safe_dump(config))
    client.app.state.mongo.settings.pipeline_config = path
    m = meeting(client)
    response = client.post(
        f"/api/v1/meetings/{m['id']}/sources?revision={m['revision']}",
        files=[("files", ("too-long.wav", wav_bytes(), "audio/wav"))],
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "AUDIO_DURATION_LIMIT"
    assert client.app.state.mongo.db.sources.count_documents({}) == 0
    assert client.app.state.mongo.db.artifacts.count_documents({}) == 0
    assert client.get(f"/api/v1/meetings/{m['id']}").json()["revision"] == m["revision"]


@pytest.mark.parametrize("duration,status", [(7200, 201), (7200 + 1 / 16000, 422)])
def test_audio_upload_accepts_two_hours_and_rejects_one_sample_over(
    client, monkeypatch, duration, status
):
    from meeting_backend.infrastructure.artifacts import media
    from meeting_pipeline.adapters.audio_io import AudioMetadata

    # Exercise HTTP admission/rollback without allocating a two-hour upload in RAM.
    monkeypatch.setattr(
        media,
        "probe_audio_metadata",
        lambda *a, **kw: AudioMetadata("pcm_s16le", 16000, 1, duration),
    )
    m = meeting(client)
    response = client.post(
        f"/api/v1/meetings/{m['id']}/sources?revision={m['revision']}",
        files=[("files", ("recording.wav", wav_bytes(), "audio/wav"))],
    )
    assert response.status_code == status
    mongo = client.app.state.mongo
    if status == 201:
        assert mongo.db.sources.find_one({"meeting_id": m["id"]})["duration_sec"] == 7200
        assert mongo.db.artifacts.count_documents({}) == 1
    else:
        assert response.json()["error"]["code"] == "AUDIO_DURATION_LIMIT"
        assert mongo.db.sources.count_documents({}) == 0
        assert mongo.db.artifacts.count_documents({}) == 0
        assert client.get(f"/api/v1/meetings/{m['id']}").json()["revision"] == m["revision"]


def test_timeline_intervals_are_independent_and_file_removal_keeps_artifact(client):
    m = upload_audio(client, meeting(client))
    view = read_timeline(client, m["id"])
    clip_id = view["timeline"]["clips"][0]["id"]
    operations = [
        {
            "op": "upsert_interval",
            "interval": {
                "id": name,
                "kind": kind,
                "start_ms": start,
                "end_ms": end,
                "start_clip_id": clip_id,
                "end_clip_id": clip_id,
                "confirmed": True,
            },
        }
        for name, kind, start, end in [
            ("session-a", "session", 0, 400),
            ("rest", "break", 400, 600),
            ("session-b", "session", 600, 1000),
        ]
    ]
    result = edit_timeline(client, m["id"], view, operations)
    result.raise_for_status()
    after = result.json()
    assert len(after["timeline"]["clips"]) == 1
    assert len(after["timeline"]["intervals"]) == 3
    assert after["processing"]["supported"] is True
    assert (
        edit_timeline(
            client,
            m["id"],
            after,
            [
                {"op": "remove_clip", "clip_id": clip_id},
            ],
        ).status_code
        == 422
    )
    assert (
        client.request(
            "DELETE",
            f"/api/v1/meetings/{m['id']}/sources/{m['source_ids'][0]}",
            json={"revision": after["revision"]},
        ).status_code
        == 409
    )
    removed = edit_timeline(
        client,
        m["id"],
        after,
        [
            *[
                {"op": "remove_interval", "interval_id": name}
                for name in ("session-a", "rest", "session-b")
            ],
            {"op": "remove_clip", "clip_id": clip_id},
        ],
    )
    removed.raise_for_status()
    unplaced = removed.json()
    assert unplaced["timeline"]["unassigned_asset_ids"] == m["source_ids"]
    response = client.request(
        "DELETE",
        f"/api/v1/meetings/{m['id']}/sources/{m['source_ids'][0]}",
        json={"revision": unplaced["revision"]},
    )
    response.raise_for_status()
    assert client.app.state.mongo.db.artifacts.find_one({"_id": m["source_ids"][0]})


def test_worker_rechecks_layout_before_loading_models(client):
    from types import SimpleNamespace

    from meeting_backend.core.errors import AppError
    from meeting_backend.integrations.audio_pipeline import transcribe

    m = upload_audio(client, meeting(client))
    mongo = client.app.state.mongo
    stored = mongo.db.meetings.find_one({"_id": m["id"]})
    context = SimpleNamespace(
        mongo=mongo,
        job={"payload": {"input_timeline_hash": "old-hash"}},
        stage=lambda message: None,
        resource=lambda: stored,
    )
    with pytest.raises(AppError) as error:
        transcribe(context)
    assert error.value.code == "INPUT_CHANGED"
    view = read_timeline(client, m["id"])
    result = edit_timeline(
        client,
        m["id"],
        view,
        [
            {
                "op": "remove_clip",
                "clip_id": view["timeline"]["clips"][0]["id"],
            },
        ],
    )
    result.raise_for_status()
    stored = mongo.db.meetings.find_one({"_id": m["id"]})
    context.job = {"payload": {}}
    with pytest.raises(AppError) as error:
        transcribe(context)
    assert error.value.code == "TIMELINE_PROCESSING_NOT_READY"


def test_timeline_track_limit_is_distinct_from_file_limit(client):
    m = meeting(client)
    view = read_timeline(client, m["id"])
    response = edit_timeline(
        client,
        m["id"],
        view,
        [
            {"op": "create_track", "id": f"track-{index}", "name": f"Máy {index}"}
            for index in range(9)
        ],
    )
    assert response.status_code == 422
    assert read_timeline(client, m["id"])["timeline"]["tracks"] == []


def test_timeline_wall_clock_needs_timezone_and_keeps_manual_provenance(client):
    m = meeting(client)
    view = read_timeline(client, m["id"])
    assert (
        edit_timeline(
            client,
            m["id"],
            view,
            [
                {"op": "set_clock_origin", "value": {"iso_time": "2026-10-27T09:00:00"}},
            ],
        ).status_code
        == 422
    )
    result = edit_timeline(
        client,
        m["id"],
        view,
        [
            {"op": "set_clock_origin", "value": {"iso_time": "2026-10-27T09:00:00+07:00"}},
        ],
    )
    result.raise_for_status()
    saved = result.json()
    assert saved["timeline"]["clock_origin"] == {
        "iso_time": "2026-10-27T02:00:00+00:00",
        "origin": "user",
        "status": "declared",
    }
    assert (
        read_timeline(client, m["id"])["timeline"]["clock_origin"]
        == saved["timeline"]["clock_origin"]
    )


def test_timeline_concurrent_edits_only_one_revision_wins(client):
    from concurrent.futures import ThreadPoolExecutor

    m = upload_audio(client, meeting(client))
    view = read_timeline(client, m["id"])
    track_id = view["timeline"]["tracks"][0]["id"]

    def rename(name):
        return edit_timeline(
            client,
            m["id"],
            view,
            [
                {"op": "update_track", "track_id": track_id, "name": name},
            ],
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(rename, ["Điện thoại A", "Điện thoại B"]))
    assert sorted(response.status_code for response in responses) == [200, 409]
    saved = read_timeline(client, m["id"])
    assert saved["revision"] == view["revision"] + 1
    assert saved["timeline"]["tracks"][0]["name"] in {"Điện thoại A", "Điện thoại B"}


def test_timeline_many_files_keep_existing_aggregate_byte_budget(client):
    mongo = client.app.state.mongo
    mongo.settings.max_sources = 1
    mongo.settings.max_upload_bytes = 50_000
    m = meeting(client)
    response = client.post(
        f"/api/v1/meetings/{m['id']}/sources",
        params={"revision": m["revision"], "timeline_mode": "true"},
        files=[("files", (f"part-{i}.wav", wav_bytes(), "audio/wav")) for i in range(2)],
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "SOURCE_STORAGE_LIMIT"
    assert mongo.db.sources.count_documents({}) == 0
    assert mongo.db.artifacts.count_documents({}) == 0


def test_transcript_edit_and_restore_keep_their_own_input_timeline(client):
    m = meeting(client)
    mongo = client.app.state.mongo
    record = mongo.db.meetings.find_one({"_id": m["id"]})
    original = create_version(
        mongo,
        record,
        [
            {
                "turn_id": "turn-a",
                "text": "Nội dung gốc",
                "speaker_count": 1,
                "speaker_label": "A",
                "speaker_key": "speaker-a",
                "start_sec": 0,
                "end_sec": 1,
            }
        ],
        reason="Original",
        input_timeline_hash="layout-a",
    )
    mongo.db.meetings.update_one(
        {"_id": m["id"]},
        {
            "$set": {
                "active_transcript_id": original["_id"],
                "state": "transcript_ready",
            }
        },
    )
    row = rows_for(mongo, original["_id"])[0]
    edited = client.patch(
        f"/api/v1/meetings/{m['id']}/transcript",
        json={
            "revision": m["revision"],
            "segment_id": row["_id"],
            "text": "Nội dung đã sửa",
        },
    )
    edited.raise_for_status()
    edited_version = mongo.db.transcript_versions.find_one(
        {
            "_id": edited.json()["active_transcript_id"],
        }
    )
    assert edited_version["input_timeline_hash"] == "layout-a"
    current = mongo.db.meetings.find_one({"_id": m["id"]})
    newer = create_version(mongo, current, [], reason="New source", input_timeline_hash="layout-b")
    mongo.db.meetings.update_one(
        {"_id": m["id"]},
        {
            "$set": {
                "active_transcript_id": newer["_id"],
            }
        },
    )
    restored = client.post(
        f"/api/v1/meetings/{m['id']}/transcript/restore",
        json={
            "revision": current["revision"],
            "version_id": original["_id"],
        },
    )
    restored.raise_for_status()
    restored_version = mongo.db.transcript_versions.find_one(
        {
            "_id": restored.json()["active_transcript_id"],
        }
    )
    assert restored_version["input_timeline_hash"] == "layout-a"
    assert restored.json()["state"] == "draft"
    assert restored.json()["transcript_stale"] is True


def test_recording_timeline_worker_publishes_local_clocks_and_review_gate(client, monkeypatch):
    import json
    from pathlib import Path

    import soundfile as sf

    from meeting_pipeline.pipeline import timeline_audio

    original = timeline_audio.TimelineAudioPipeline

    class TinyCore:
        def __init__(self, config):
            self.config = config

        def run(self, name, paths, profiles, **kwargs):
            run = self.config.paths.data_dir / uuid4().hex
            (run / "clips").mkdir(parents=True)
            samples, sr = sf.read(paths[0], dtype="float32")
            sf.write(run / "clips/evidence.wav", samples, sr)
            row = {
                "segment_id": "turn-0",
                "start_sec": 0,
                "end_sec": len(samples) / sr,
                "text": "Nội dung họp",
                "asr_status": "transcribed",
                "speaker_count": 1,
                "speaker_label": "Người 1",
                "speaker_id": "anon-1",
                "meeting_speaker_id": "ms-1",
                "speaker_status": "anonymous",
                "selected_source_id": "source-1",
                "evidence_clip_artifact_id": "clips/evidence.wav",
            }
            (run / "timeline.json").write_text(json.dumps({"segments": [row]}))
            (run / "manifest.json").write_text(json.dumps({"models": {}, "sources": []}))
            return run

    monkeypatch.setattr(
        timeline_audio, "TimelineAudioPipeline", lambda config: original(config, TinyCore)
    )
    m = upload_audio(client, meeting(client), count=2)
    view = read_timeline(client, m["id"])
    first, second = view["timeline"]["tracks"]
    result = edit_timeline(
        client,
        m["id"],
        view,
        [
            {
                "op": "move_clip",
                "clip_id": second["clip_ids"][0],
                "track_id": first["id"],
            }
        ],
    )
    result.raise_for_status()
    placed = result.json()
    assert placed["processing"]["mode"] == "timeline"
    queued = client.post(
        f"/api/v1/meetings/{m['id']}/process", json={"revision": placed["revision"]}
    )
    queued.raise_for_status()
    assert Runner(client.app.state.mongo).run_once()
    job = client.get(f"/api/v1/jobs/{queued.json()['id']}").json()
    assert job["state"] == "succeeded", job
    transcript = client.get(f"/api/v1/meetings/{m['id']}/transcript").json()
    assert transcript["version"]["timing_complete"] is False
    assert len(transcript["segments"]) == 2
    local = next(row for row in transcript["segments"] if row["time_status"] == "unresolved")
    assert local["meeting_start_sec"] is None and local["clip"]
    assert {
        ev["asset_id"] for row in transcript["segments"] for ev in row["recording_evidence"]
    } == set(m["source_ids"])
    current = client.get(f"/api/v1/meetings/{m['id']}").json()
    assert current["duration_sec"] is None
    assert current["processing_summary"]["component_count"] == 2
    aligned = read_timeline(client, m["id"])
    assert aligned["last_alignment"] and aligned["alignment_stale"] is False
    report = client.get(aligned["last_alignment"]["url"])
    assert report.status_code == 200 and report.json()["timing_complete"] is False
    blocked = client.post(
        f"/api/v1/meetings/{m['id']}/minutes/generate",
        json={
            "revision": current["revision"],
            "template_id": "unused",
        },
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "TIMELINE_REVIEW_REQUIRED"
    version = client.app.state.mongo.db.transcript_versions.find_one(
        {
            "_id": current["active_transcript_id"],
        }
    )
    assert Path(version["run_path"], "input_timeline.json").is_file()


def test_auth_csrf_and_role_enforcement(client):
    assert (
        client.post(
            "/api/v1/auth/setup",
            json={"username": "evil", "password": PASSWORD, "display_name": "X"},
        ).status_code
        == 409
    )
    token = client.headers.pop("X-CSRF-Token")
    assert client.post("/api/v1/meetings", json={"title": "X"}).status_code == 403
    client.headers["X-CSRF-Token"] = token
    assert (
        client.post(
            "/api/v1/meetings", json={"title": "X"}, headers={"Origin": "https://foreign.test"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/admin/users",
            json={"username": "member", "password": PASSWORD, "display_name": "Member"},
        ).status_code
        == 201
    )
    login(client, "member")
    assert client.get("/api/v1/admin/overview").status_code == 403
    assert client.get("/api/v1/admin/users").status_code == 403


def test_ownership_and_revision(client):
    m = meeting(client)
    assert (
        client.patch(
            f"/api/v1/meetings/{m['id']}", json={"revision": 1, "title": "Mới"}
        ).status_code
        == 200
    )
    assert (
        client.patch(f"/api/v1/meetings/{m['id']}", json={"revision": 1, "title": "Cũ"}).status_code
        == 409
    )
    client.post(
        "/api/v1/admin/users",
        json={"username": "member", "password": PASSWORD, "display_name": "Member"},
    ).raise_for_status()
    login(client, "member")
    assert client.get(f"/api/v1/meetings/{m['id']}").status_code == 404
    assert client.get("/api/v1/meetings").json()["total"] == 0


def test_invalid_audio_does_not_publish_source(client):
    m = meeting(client)
    result = client.post(
        f"/api/v1/meetings/{m['id']}/sources?revision=1",
        files=[("files", ("bad.wav", b"not audio", "audio/wav"))],
    )
    assert result.status_code == 422
    assert client.get("/api/v1/meetings/" + m["id"]).json()["source_ids"] == []
    assert client.app.state.mongo.db.artifacts.count_documents({}) == 0


def test_admin_lists_users_and_meetings_across_owners_without_private_content(client):
    own = meeting(client)
    created = client.post(
        "/api/v1/admin/users",
        json={"username": "member", "password": PASSWORD, "display_name": "Thành viên (QA)"},
    )
    created.raise_for_status()
    member_id = created.json()["id"]
    login(client, "member")
    other = client.post(
        "/api/v1/meetings", json={"title": "[QA] Họp nhóm", "notes": "private notes"}
    ).json()
    trashed = meeting(client)
    mongo = client.app.state.mongo
    mongo.db.meetings.update_one({"_id": trashed["id"]}, {"$set": {"trashed": True}})
    assert client.get("/api/v1/admin/meetings").status_code == 403
    assert client.get("/api/v1/admin/users").status_code == 403
    assert client.get("/api/v1/meetings").json()["total"] == 1
    login(client, "admin")
    accounts = client.get("/api/v1/admin/users").json()
    assert len(accounts) == 2
    member = next(account for account in accounts if account["id"] == member_id)
    assert member["meeting_count"] == 1 and member["trashed_meeting_count"] == 1
    assert "password_hash" not in member
    response = client.get("/api/v1/admin/meetings")
    response.raise_for_status()
    result = response.json()
    assert result["total"] == 2
    assert {row["id"] for row in result["items"]} == {own["id"], other["id"]}
    other_row = next(row for row in result["items"] if row["id"] == other["id"])
    assert other_row["owner_name"] == "Thành viên (QA)"
    assert other_row["owner_username"] == "member"
    assert (
        not {"notes", "source_ids", "active_transcript_id", "active_minutes_id"} & other_row.keys()
    )
    # Seeing management metadata does not change the private workspace's access rules.
    assert client.get("/api/v1/meetings/" + other["id"]).status_code == 404
    assert client.get("/api/v1/meetings").json()["total"] == 1
    assert client.get("/api/v1/admin/meetings", params={"trashed": "all"}).json()["total"] == 3
    rows = client.get(
        "/api/v1/admin/meetings", params={"owner_id": member_id, "trashed": "trashed"}
    ).json()["items"]
    assert [row["id"] for row in rows] == [trashed["id"]]
    for phrase in ["[QA]", "(QA)", "member"]:
        assert client.get("/api/v1/admin/meetings", params={"q": phrase}).json()["total"] == 1
    assert client.get("/api/v1/admin/meetings", params={"q": "[.*]"}).json()["total"] == 0
    first = client.get("/api/v1/admin/meetings", params={"limit": 1}).json()
    second = client.get("/api/v1/admin/meetings", params={"limit": 1, "page": 2}).json()
    assert first["total"] == second["total"] == 2
    assert first["items"][0]["id"] != second["items"][0]["id"]
    assert (
        client.get("/api/v1/admin/meetings", params={"state": "minutes_ready"}).json()["total"] == 0
    )
    mongo.db.meetings.update_one({"_id": other["id"]}, {"$set": {"active_job": "test-job"}})
    assert client.get("/api/v1/admin/meetings", params={"state": "processing"}).json()["total"] == 1
    assert client.get("/api/v1/admin/meetings", params={"limit": 101}).status_code == 422


def test_admin_user_filters_include_locked_accounts(client):
    response = client.post(
        "/api/v1/admin/users",
        json={"username": "locked", "password": PASSWORD, "display_name": "Tài khoản đã khóa"},
    )
    response.raise_for_status()
    client.patch(
        "/api/v1/admin/users/" + response.json()["id"], json={"active": False}
    ).raise_for_status()
    accounts = client.get("/api/v1/admin/users").json()
    assert len(accounts) == 2
    assert len(client.get("/api/v1/admin/users", params={"active": "false"}).json()) == 1
    assert len(client.get("/api/v1/admin/users", params={"role": "admin"}).json()) == 1
    assert len(client.get("/api/v1/admin/users", params={"q": "locked"}).json()) == 1
    assert client.get("/api/v1/admin/users", params={"q": "[.*]"}).json() == []


def test_artifact_permissions_and_shared_template_revocation(client, tmp_path):
    from meeting_backend.infrastructure.artifacts.store import ArtifactStore

    mongo = client.app.state.mongo
    admin = mongo.db.users.find_one({"username": "admin"})
    private = tmp_path / "private.txt"
    private.write_text("private data")
    shared = tmp_path / "shared.txt"
    shared.write_text("shared template")
    store = ArtifactStore(mongo)
    private_art = store.register(private, admin["_id"], resource_id="private-resource")
    shared_art = store.register(shared, admin["_id"], resource_id="shared-template")
    mongo.db.templates.insert_one(
        {
            "_id": "shared-template",
            "owner_id": admin["_id"],
            "visibility": "shared",
            "trashed": False,
            "state": "ready",
            "revision": 1,
            "active_job": None,
        }
    )
    client.post(
        "/api/v1/admin/users",
        json={"username": "member", "password": PASSWORD, "display_name": "Member"},
    ).raise_for_status()
    login(client, "member")
    assert client.get("/api/v1/artifacts/" + private_art["_id"]).status_code == 404
    assert client.get("/api/v1/artifacts/" + shared_art["_id"]).text == "shared template"
    assert (
        client.post("/api/v1/templates/shared-template/archive", json={"revision": 1}).status_code
        == 409
    )
    login(client, "admin")
    client.post(
        "/api/v1/templates/shared-template/archive", json={"revision": 1}
    ).raise_for_status()
    login(client, "member")
    assert client.get("/api/v1/artifacts/" + shared_art["_id"]).status_code == 404


def test_admin_can_cancel_another_users_job_with_audit(client):
    from meeting_backend.modules.jobs.service import enqueue

    client.post(
        "/api/v1/admin/users",
        json={"username": "member", "password": PASSWORD, "display_name": "Member"},
    ).raise_for_status()
    login(client, "member")
    m = meeting(client)
    mongo = client.app.state.mongo
    owner = mongo.db.users.find_one({"username": "member"})
    job = enqueue(mongo, owner, "meeting", m["id"], "unsupported")
    login(client, "admin")
    response = client.post("/api/v1/admin/jobs/" + job["id"] + "/cancel")
    response.raise_for_status()
    assert response.json()["state"] == "cancelled"
    event = mongo.db.audit_events.find_one({"action": "admin_job_cancel", "resource_id": job["id"]})
    assert event["owner_id"] != owner["_id"] and event["details"]["owner_id"] == owner["_id"]


def test_cancelled_or_replaced_lease_cannot_publish(client):
    from meeting_backend.modules.jobs.service import enqueue
    from meeting_backend.worker.context import Cancelled, Context

    m = meeting(client)
    mongo = client.app.state.mongo
    user = mongo.db.users.find_one({"username": "admin"})
    job = enqueue(mongo, user, "meeting", m["id"], "unsupported")
    mongo.db.jobs.update_one(
        {"_id": job["id"]},
        {
            "$set": {
                "state": "running",
                "lease_token": "old",
                "lease_until": datetime.now(UTC) + timedelta(seconds=60),
            }
        },
    )
    context = Context(mongo, mongo.db.jobs.find_one({"_id": job["id"]}))
    mongo.db.jobs.update_one({"_id": job["id"]}, {"$set": {"cancel_requested": True}})
    with pytest.raises(Cancelled):
        context.publish({"title": "must not publish"})
    mongo.db.jobs.update_one(
        {"_id": job["id"]}, {"$set": {"cancel_requested": False, "lease_token": "new"}}
    )
    with pytest.raises(Cancelled):
        context.publish({"title": "must not publish"})
    assert mongo.db.meetings.find_one({"_id": m["id"]})["title"] == m["title"]


def test_minutes_export_context_matches_database_ids_and_zip(tmp_path):
    import hashlib
    import json
    import zipfile

    from docx import Document

    from meeting_backend.integrations.minutes_pipeline import stamp_export_context, validate_export

    run = tmp_path / "run"
    (run / "minutes").mkdir(parents=True)
    (run / "exports").mkdir()
    document = Document()
    document.add_paragraph("Nội dung không bị thay đổi khi gắn ID.")
    docx = run / "exports/completed.docx"
    document.save(docx)
    original = docx.read_bytes()
    manifest = {
        "run_id": "old-run",
        "meeting_id": "staging",
        "completed_docx_sha256": hashlib.sha256(original).hexdigest(),
    }
    (run / "minutes/manifest.json").write_text(json.dumps(manifest))
    with zipfile.ZipFile(run / "exports/completed_minutes.zip", "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.write(docx, "completed.docx")
    stamp_export_context(
        run,
        meeting_id="meeting-uuid",
        job_id="job-uuid",
        transcript_version_id="transcript-uuid",
        input_content_revision=3,
    )
    validate_export(run)
    assert docx.read_bytes() == original
    with zipfile.ZipFile(run / "exports/completed_minutes.zip") as archive:
        assert archive.namelist().count("manifest.json") == 1
        saved = json.loads(archive.read("manifest.json"))
        assert saved["meeting_id"] == "meeting-uuid" and saved["run_id"] == "job-uuid"
        assert saved["app_context"]["input_content_revision"] == 3


def test_session_expiry_and_account_lock(client):
    mongo = client.app.state.mongo
    mongo.db.sessions.update_many(
        {}, {"$set": {"expires_at": datetime.now(UTC) - timedelta(seconds=1)}}
    )
    assert client.get("/api/v1/auth/me").status_code == 401
    login(client, "admin")
    admin = mongo.db.users.find_one({"username": "admin"})
    mongo.db.users.update_one({"_id": admin["_id"]}, {"$set": {"active": False}})
    assert client.get("/api/v1/auth/me").status_code == 401


def test_upload_job_cancel_and_removed_source(client):
    m = meeting(client)
    uploaded = client.post(
        f"/api/v1/meetings/{m['id']}/sources?revision=1",
        files=[("files", ("clip.wav", BytesIO(wav_bytes()), "audio/wav"))],
    )
    uploaded.raise_for_status()
    m = uploaded.json()
    job = client.post(f"/api/v1/meetings/{m['id']}/process", json={"revision": m["revision"]})
    job.raise_for_status()
    assert (
        client.patch(
            f"/api/v1/meetings/{m['id']}", json={"revision": m["revision"] + 1, "title": "blocked"}
        ).status_code
        == 409
    )
    assert client.post(f"/api/v1/jobs/{job.json()['id']}/cancel").json()["state"] == "cancelled"
    m = client.get(f"/api/v1/meetings/{m['id']}").json()
    deleted = client.request(
        "DELETE",
        f"/api/v1/meetings/{m['id']}/sources/{m['source_ids'][0]}",
        json={"revision": m["revision"]},
    ).json()
    assert (
        client.post(
            f"/api/v1/meetings/{m['id']}/process", json={"revision": deleted["revision"]}
        ).status_code
        == 422
    )


def test_transcript_revisions_preserve_evidence_and_stale(client):
    m = meeting(client)
    mongo = client.app.state.mongo
    raw = mongo.db.meetings.find_one({"_id": m["id"]})
    version = create_version(
        mongo,
        raw,
        [
            {
                "text": "cũ",
                "speaker_label": "An",
                "speaker_key": "speaker:1",
                "speaker_count": 1,
                "turn_id": "t1",
                "start_sec": 0,
                "end_sec": 2,
                "clip": {"id": "evidence"},
                "data": {"text": "cũ", "confidence": 0.7},
            }
        ],
        reason="test",
    )
    mongo.db.meetings.update_one(
        {"_id": m["id"]},
        {
            "$set": {
                "active_transcript_id": version["_id"],
                "active_minutes_id": "prior",
                "content_revision": 1,
            }
        },
    )
    old = rows_for(mongo, version["_id"])[0]
    response = client.patch(
        f"/api/v1/meetings/{m['id']}/transcript",
        json={"revision": 1, "segment_id": old["_id"], "text": "mới"},
    )
    response.raise_for_status()
    updated = response.json()
    assert updated["minutes_stale"] is True
    new = rows_for(mongo, updated["active_transcript_id"])[0]
    assert new["clip"] == old["clip"] and new["data"]["confidence"] == 0.7
    assert rows_for(mongo, version["_id"])[0]["text"] == "cũ"
    renamed = client.post(
        f"/api/v1/meetings/{m['id']}/speakers/rename",
        json={"revision": updated["revision"], "speaker_key": "speaker:1", "label": "Anh An"},
    )
    renamed.raise_for_status()
    assert rows_for(mongo, renamed.json()["active_transcript_id"])[0]["speaker_key"] == "speaker:1"


def test_worker_failure_recovery_and_retry(client):
    from meeting_backend.modules.jobs.service import enqueue

    m = meeting(client)
    mongo = client.app.state.mongo
    user = mongo.db.users.find_one({"username": "admin"})
    job = enqueue(mongo, user, "meeting", m["id"], "unsupported")
    assert Runner(mongo).run_once()
    saved = mongo.db.jobs.find_one({"_id": job["id"]})
    assert saved["state"] == "failed" and saved["error"]["code"] == "UNKNOWN_JOB"
    assert mongo.db.meetings.find_one({"_id": m["id"]})["active_job"] is None
    retry = client.post(f"/api/v1/jobs/{job['id']}/retry")
    assert retry.status_code == 202
    jid = retry.json()["id"]
    mongo.db.jobs.update_one(
        {"_id": jid},
        {
            "$set": {
                "state": "running",
                "lease_until": datetime.now(UTC) - timedelta(seconds=3),
                "lease_token": "dead",
            }
        },
    )
    Runner(mongo).recover()
    assert mongo.db.jobs.find_one({"_id": jid})["state"] == "interrupted"


def test_backup_restore_to_separate_database(client):
    m = meeting(client)
    mongo = client.app.state.mongo
    job = client.post("/api/v1/admin/backups").json()
    Runner(mongo).run_once()
    saved = mongo.db.jobs.find_one({"_id": job["id"]})
    assert saved["state"] == "succeeded", saved.get("error")
    artifact = saved["result"]["backup"]
    assert client.get(artifact["url"] + "?download=true").status_code == 200
    restore = client.post(
        "/api/v1/admin/restore",
        json={"confirmation": "RESTORE_TO_NEW_DATABASE", "artifact_id": artifact["id"]},
    ).json()
    Runner(mongo).run_once()
    restored = mongo.db.jobs.find_one({"_id": restore["id"]})
    assert restored["state"] == "succeeded", restored.get("error")
    database = restored["result"]["database"]
    try:
        assert database != mongo.settings.mongo_database
        assert mongo.client[database].meetings.find_one({"_id": m["id"]})
        assert mongo.client[database].sessions.count_documents({}) == 0
        assert mongo.db.meetings.find_one({"_id": m["id"]})
    finally:
        mongo.client.drop_database(database)


def test_invalid_backup_zip_cannot_escape(client, tmp_path):
    import zipfile

    blob = BytesIO()
    with zipfile.ZipFile(blob, "w") as archive:
        archive.writestr("../../escape.txt", "malicious")
    uploaded = client.post(
        "/api/v1/admin/backups/upload",
        files={"file": ("bad.zip", blob.getvalue(), "application/zip")},
    ).json()
    job = client.post(
        "/api/v1/admin/restore",
        json={"confirmation": "RESTORE_TO_NEW_DATABASE", "artifact_id": uploaded["id"]},
    ).json()
    Runner(client.app.state.mongo).run_once()
    assert client.app.state.mongo.db.jobs.find_one({"_id": job["id"]})["state"] == "failed"
    assert not (tmp_path / "escape.txt").exists()


@pytest.mark.parametrize("kind", ["docx", "doc", "text_pdf", "scan_pdf", "png"])
def test_document_ingestion_and_review(client, tmp_path, kind):
    import shutil
    import subprocess

    from docx import Document
    from PIL import Image, ImageDraw, ImageFont

    from meeting_backend.infrastructure.artifacts.store import ArtifactStore

    if not shutil.which("soffice") or not shutil.which("pdftoppm"):
        pytest.skip("Document integration requires LibreOffice and Poppler")
    document = Document()
    document.add_heading("BIÊN BẢN CUỘC HỌP", 0)
    document.add_paragraph("Ngày họp: .................................")
    document.add_paragraph("Chủ trì: .................................")
    document.add_heading("I. NỘI DUNG CUỘC HỌP", 1)
    document.add_paragraph("Nội dung: ........................................................")
    source = tmp_path / "source.docx"
    document.save(source)
    if kind in {"doc", "text_pdf"}:
        extension = "doc:MS Word 97" if kind == "doc" else "pdf"
        output = tmp_path / "converted"
        output.mkdir()
        result = subprocess.run(
            [
                shutil.which("soffice"),
                "--headless",
                f"-env:UserInstallation={(tmp_path / 'lo-profile').as_uri()}",
                "--convert-to",
                extension,
                "--outdir",
                str(output),
                str(source),
            ],
            capture_output=True,
            timeout=60,
        )
        assert result.returncode == 0
        source = output / ("source.doc" if kind == "doc" else "source.pdf")
    elif kind in {"scan_pdf", "png"}:
        if not shutil.which("tesseract"):
            pytest.skip("Tesseract required")
        image = Image.new("RGB", (1800, 1400), "white")
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 38)
        for y, text in [
            (90, "BIÊN BẢN CUỘC HỌP"),
            (220, "Ngày họp: ........................................"),
            (340, "Chủ trì: ........................................"),
            (470, "I. NỘI DUNG CUỘC HỌP"),
            (590, "Nội dung: ................................................"),
        ]:
            draw.text((100, y), text, fill="black", font=font)
        for y in [800, 930, 1060]:
            draw.line([(100, y), (1600, y)], fill="black", width=3)
        for x in [100, 800, 1600]:
            draw.line([(x, 800), (x, 1060)], fill="black", width=3)
        for x, y, text in [
            (130, 840, "Người phụ trách"),
            (840, 840, "Công việc"),
            (130, 970, "Nguyễn Văn An"),
            (840, 970, "Chuẩn bị tài liệu"),
        ]:
            draw.text((x, y), text, fill="black", font=font)
        source = tmp_path / ("scan.pdf" if kind == "scan_pdf" else "scan.png")
        image.save(source)
    response = client.post(
        "/api/v1/templates",
        data={"name": f"Test {kind}"},
        files={"file": (source.name, source.read_bytes())},
    )
    response.raise_for_status()
    tid = response.json()["template_id"]
    runner = Runner(client.app.state.mongo)
    runner.run_once()
    job = client.app.state.mongo.db.jobs.find_one({"_id": response.json()["job"]["id"]})
    assert job["state"] == "succeeded", job.get("error")
    template = client.get("/api/v1/templates/" + tid).json()
    assert template["version"]["previews"]
    assert template["needs_review"] == (kind not in {"doc", "docx"})
    artifact = client.app.state.mongo.db.artifacts.find_one(
        {"_id": template["version"]["normalized"]["id"]}
    )
    normalized = Document(ArtifactStore(client.app.state.mongo).resolve(artifact))
    assert any(p.text.strip() for p in normalized.paragraphs)
    if kind in {"scan_pdf", "png"}:
        assert template["version"]["report"]["pages"][0]["table_count"] >= 1
        assert normalized.tables
    review = client.post(
        "/api/v1/templates/" + tid + "/review",
        json={
            "revision": template["revision"],
            "fields": template["version"]["schema"]["fields"],
            "approved": True,
        },
    )
    review.raise_for_status()
    runner.run_once()
    job = client.app.state.mongo.db.jobs.find_one({"_id": review.json()["id"]})
    assert job["state"] == "succeeded", job.get("error")
    assert client.get("/api/v1/templates/" + tid).json()["needs_review"] is False


def test_preview_repair_preserves_content_and_shared_template_permissions(
    client, tmp_path, monkeypatch
):
    import hashlib

    from docx import Document
    from PIL import Image

    from meeting_backend.infrastructure.artifacts.store import ArtifactStore
    from meeting_backend.processing.documents.previews import repair_previews
    from meeting_pipeline.minutes.document_tools import preview_tools

    # Reproduce a normal Terminal with no Codex runtime paths or Homebrew PATH entry.
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    if not all(preview_tools().values()):
        pytest.skip("Install system LibreOffice/Poppler for this real rendering test")
    mongo = client.app.state.mongo
    store = ArtifactStore(mongo)
    owner = mongo.db.users.find_one({"username": "admin"})["_id"]
    template_id, template_version_id, minutes_version_id = [uuid4().hex for _ in range(3)]
    meeting_id = meeting(client)["id"]
    document = Document()
    document.add_heading("BIÊN BẢN CUỘC HỌP", 0)
    document.add_paragraph("Nội dung đã được người dùng kiểm tra.")
    document.add_page_break()
    document.add_paragraph("Trang thứ hai: quyết định và người thực hiện.")
    sources = {}
    for name, resource in [("template", template_id), ("minutes", meeting_id)]:
        path = tmp_path / f"{name}.docx"
        document.save(path)
        sources[name] = store.view(store.register(path, owner, resource_id=resource))
    mongo.db.templates.insert_one(
        {"_id": template_id, "owner_id": owner, "visibility": "shared", "trashed": False}
    )
    mongo.db.template_versions.insert_one(
        {
            "_id": template_version_id,
            "template_id": template_id,
            "owner_id": owner,
            "normalized": sources["template"],
            "previews": [],
            "report": {"preview_error": "missing tools", "needs_review": False},
        }
    )
    facts = [{"field_id": "content", "value": "Nội dung đã sửa", "user_edited": True}]
    archive = tmp_path / "original.zip"
    archive.write_bytes(b"unchanged original archive")
    mongo.db.minutes_versions.insert_one(
        {
            "_id": minutes_version_id,
            "meeting_id": meeting_id,
            "owner_id": owner,
            "docx": sources["minutes"],
            "zip": store.view(store.register(archive, owner, resource_id=meeting_id)),
            "previews": [],
            "facts": facts,
            "formatting": {"preview_error": "missing tools", "standard": "nd30_2020"},
        }
    )
    mongo.db.meetings.update_one(
        {"_id": meeting_id},
        {"$set": {"active_minutes_id": minutes_version_id, "reviewed_version": minutes_version_id}},
    )
    paths = [tmp_path / "template.docx", tmp_path / "minutes.docx", archive]
    hashes = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    artifact_count = mongo.db.artifacts.count_documents({})
    assert len(repair_previews(mongo)["versions"]) == 2
    assert mongo.db.artifacts.count_documents({}) == artifact_count
    result = repair_previews(mongo, apply=True)
    assert result["repaired"] == 2 and result["failed"] == 0, result
    for collection, version_id in [
        ("template_versions", template_version_id),
        ("minutes_versions", minutes_version_id),
    ]:
        version = mongo.db[collection].find_one({"_id": version_id})
        assert len(version["previews"]) == 2
        for page in version["previews"]:
            response = client.get(page["url"])
            assert response.status_code == 200 and response.headers["content-type"] == "image/png"
            with Image.open(BytesIO(response.content)) as image:
                image.verify()
        assert "preview_error" not in version.get("report", version.get("formatting", {}))
    assert hashes == {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    assert mongo.db.minutes_versions.find_one({"_id": minutes_version_id})["facts"] == facts
    assert mongo.db.meetings.find_one({"_id": meeting_id})["reviewed_version"] == minutes_version_id
    assert not repair_previews(mongo, apply=True)["versions"]
    client.post(
        "/api/v1/admin/users",
        json={"username": "reader", "password": PASSWORD, "display_name": "Reader"},
    ).raise_for_status()
    login(client, "reader")
    shared = mongo.db.template_versions.find_one({"_id": template_version_id})["previews"][0]
    private = mongo.db.minutes_versions.find_one({"_id": minutes_version_id})["previews"][0]
    assert client.get(shared["url"]).status_code == 200
    assert client.get(private["url"]).status_code == 404


def test_legacy_import_is_read_only_dry_run_and_idempotent(client, tmp_path):
    import hashlib
    import json
    import sqlite3

    from meeting_backend.integrations.legacy_import import import_legacy, import_run

    source = tmp_path / "legacy/run-1"
    source.mkdir(parents=True)
    path = source / "timeline.json"
    path.write_text(
        json.dumps(
            {
                "segments": [
                    {
                        "turn_id": "t1",
                        "text": "Nội dung gốc",
                        "speaker_label": "An",
                        "start_sec": 0,
                        "end_sec": 2,
                    }
                ]
            }
        )
    )
    original = hashlib.sha256(path.read_bytes()).hexdigest()
    mongo = client.app.state.mongo
    preview = import_run(mongo, "admin", source, dry_run=True)
    assert preview["segments"] == 1 and preview["dry_run"]
    assert mongo.db.meetings.count_documents({}) == 0
    mid = import_run(mongo, "admin", source)
    assert import_run(mongo, "admin", source) == mid
    assert mongo.db.meetings.count_documents({}) == 1
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original
    sqlite = tmp_path / "legacy.sqlite"
    with sqlite3.connect(sqlite) as db:
        db.execute("CREATE TABLE meetings (id TEXT, name TEXT)")
        db.execute("CREATE TABLE runs (id TEXT,meeting_id TEXT,status TEXT)")
        db.execute("INSERT INTO meetings VALUES ('old-1','Tên từ SQLite')")
        db.execute("INSERT INTO runs VALUES ('run-1','old-1','completed')")
    result = import_legacy(mongo, "admin", source.parent, sqlite_path=sqlite, dry_run=True)
    assert result["count"] == 1 and result["runs"][0]["result"]["existing_meeting_id"] == mid
    assert mongo.db.meetings.count_documents({}) == 1


def test_legacy_import_failure_cleans_only_its_own_records(client, tmp_path, monkeypatch):
    import json

    from meeting_backend.integrations import legacy_import

    source = tmp_path / "legacy"
    source.mkdir()
    (source / "timeline.json").write_text(json.dumps({"segments": []}))
    existing = meeting(client)
    inspect = legacy_import.inspect_run

    def fail_copied(path):
        result = inspect(path)
        if str(path).startswith(str(client.app.state.mongo.settings.data_dir / "imported")):
            result["hashes"] = {"different": "hash"}
        return result

    monkeypatch.setattr(legacy_import, "inspect_run", fail_copied)
    with pytest.raises(ValueError, match="Hash file"):
        legacy_import.import_run(client.app.state.mongo, "admin", source)
    assert client.get("/api/v1/meetings").json()["items"][0]["id"] == existing["id"]
    assert client.app.state.mongo.db.meetings.count_documents({}) == 1


def test_workspace_aggregations_speaker_detail_and_branding_static(client, tmp_path):
    mongo = client.app.state.mongo
    admin_user = client.get("/api/v1/auth/me").json()

    # 1. Verify /branding/* serves real files and returns 404 (not index.html) when missing
    web_settings = Settings(
        mongo_database="meeting_app_test_web_" + uuid4().hex,
        data_dir=tmp_path / "web_data",
        web_dist=Settings().web_dist,
    )
    web_app_instance = create_app(web_settings)
    with TestClient(web_app_instance) as web_client:
        mark_res = web_client.get("/branding/logo-mark.svg")
        assert mark_res.status_code == 200
        assert "svg" in mark_res.headers.get("content-type", "")
        fav_res = web_client.get("/branding/favicon.svg")
        assert fav_res.status_code == 200
        for url in ["/illustrations/signal.webp", "/product/transcript.webp"]:
            image = web_client.get(url)
            assert image.status_code == 200
            assert image.headers["content-type"].startswith("image/webp")
        assert web_client.get("/illustrations/missing.webp").status_code == 404
        assert web_client.get("/product/missing.webp").status_code == 404
        missing_brand = web_client.get("/branding/does-not-exist-logo.svg")
        assert missing_brand.status_code == 404
        missing_asset = web_client.get("/assets/does-not-exist.js")
        assert missing_asset.status_code == 404
        spa_res = web_client.get("/welcome")
        assert spa_res.status_code == 200
        assert "text/html" in spa_res.headers.get("content-type", "")
        web_app_instance.state.mongo.client.drop_database(web_settings.mongo_database)

    # 2. Create a speaker profile and test GET /api/v1/speakers/{id}
    speaker_created = client.post(
        "/api/v1/speakers",
        data={"name": "Nguyễn Văn A"},
        files=[("samples", ("voice.wav", wav_bytes(), "audio/wav"))],
    )
    speaker_created.raise_for_status()
    speaker_id = speaker_created.json()["speaker_id"]
    mongo.db.speakers.update_one({"_id": speaker_id}, {"$set": {"state": "ready"}})

    m1 = meeting(client)
    client.patch(
        f"/api/v1/meetings/{m1['id']}",
        json={
            "revision": m1["revision"],
            "title": "Họp giao ban tuần 1",
            "date": "2026-11-06",
            "location": "Phòng 201",
            "notes": "",
            "participant_ids": [speaker_id],
        },
    ).raise_for_status()

    sp_detail = client.get(f"/api/v1/speakers/{speaker_id}")
    sp_detail.raise_for_status()
    sp_body = sp_detail.json()
    assert sp_body["id"] == speaker_id
    assert sp_body["name"] == "Nguyễn Văn A"
    assert len(sp_body["samples"]) == 1
    assert any(item["id"] == m1["id"] for item in sp_body["meetings"])

    # 3. Populate transcript with needs_review segments & unreviewed/stale minutes
    tv_id = "tv-test-1"
    mv_id = "mv-test-1"
    mongo.db.transcript_versions.insert_one(
        {
            "_id": tv_id,
            "meeting_id": m1["id"],
            "owner_id": admin_user["id"],
            "created_at": "2026-11-06T01:00:00Z",
            "reason": "Test transcript",
        }
    )
    mongo.db.transcript_segments.insert_many(
        [
            {
                "_id": "seg-1",
                "version_id": tv_id,
                "meeting_id": m1["id"],
                "owner_id": admin_user["id"],
                "index": 0,
                "turn_id": "t-1",
                "text": "Đoạn cần kiểm tra",
                "speaker_label": "Người 1",
                "start_sec": 0.0,
                "end_sec": 2.0,
                "needs_review": True,
                "user_edited": False,
            },
            {
                "_id": "seg-2",
                "version_id": tv_id,
                "meeting_id": m1["id"],
                "owner_id": admin_user["id"],
                "index": 1,
                "turn_id": "t-2",
                "text": "Đoạn bình thường",
                "speaker_label": "Người 1",
                "start_sec": 2.0,
                "end_sec": 4.0,
                "needs_review": False,
                "user_edited": False,
            },
        ]
    )
    mongo.db.minutes_versions.insert_one(
        {
            "_id": mv_id,
            "meeting_id": m1["id"],
            "owner_id": admin_user["id"],
            "created_at": "2026-11-06T01:05:00Z",
            "reason": "Initial minutes",
            "input_content_revision": 1,
            "facts": [],
            "schema": {"fields": []},
            "options": {},
            "report": {},
            "formatting": {},
            "topics": {},
            "corrections": [],
            "previews": [],
        }
    )
    mongo.db.meetings.update_one(
        {"_id": m1["id"]},
        {
            "$set": {
                "active_transcript_id": tv_id,
                "active_minutes_id": mv_id,
                "minutes_stale": False,
                "content_revision": 1,
            }
        },
    )

    # Also insert a shared template needing review owned by admin
    mongo.db.templates.insert_one(
        {
            "_id": "tpl-shared-review",
            "owner_id": admin_user["id"],
            "name": "Mẫu chung chờ duyệt",
            "visibility": "shared",
            "state": "ready",
            "active_job": None,
            "revision": 1,
            "needs_review": True,
            "trashed": False,
            "created_at": "2026-11-06T01:10:00Z",
            "updated_at": "2026-11-06T01:10:00Z",
        }
    )

    rev_all = client.get("/api/v1/workspace/review?kind=all").json()
    assert rev_all["total"] == 2
    meeting_item = next(i for i in rev_all["items"] if i["resource_type"] == "meeting")
    assert set(meeting_item["reason_codes"]) == {
        "minutes_unreviewed",
        "transcript_needs_review",
    }

    docs_res = client.get("/api/v1/workspace/documents?review=needs_review").json()
    assert docs_res["total"] == 1
    assert docs_res["items"][0]["meeting_id"] == m1["id"]
    assert docs_res["items"][0]["review_status"] == "needs_review"

    jobs_res = client.get("/api/v1/workspace/jobs").json()
    assert jobs_res["total"] >= 1
    assert any(j["resource_id"] == speaker_id for j in jobs_res["items"])

    # 3b. Verify >30 pagination across review, documents, and jobs
    for idx in range(32):
        mongo.db.templates.insert_one(
            {
                "_id": f"tpl-bulk-{idx}",
                "owner_id": admin_user["id"],
                "name": f"Mẫu chờ duyệt {idx:02d}",
                "visibility": "private",
                "state": "ready",
                "active_job": None,
                "revision": 1,
                "needs_review": True,
                "trashed": False,
                "created_at": f"2026-11-06T02:{idx:02d}:00Z",
                "updated_at": f"2026-11-06T02:{idx:02d}:00Z",
            }
        )
        mongo.db.jobs.insert_one(
            {
                "_id": f"job-bulk-{idx}",
                "owner_id": admin_user["id"],
                "kind": "template_analyze",
                "resource_type": "template",
                "resource_id": f"tpl-bulk-{idx}",
                "state": "succeeded",
                "stage": "done",
                "progress": 100,
                "created_at": f"2026-11-06T02:{idx:02d}:00Z",
                "updated_at": f"2026-11-06T02:{idx:02d}:00Z",
            }
        )
    rev_page1 = client.get("/api/v1/workspace/review?page=1&limit=30").json()
    rev_page2 = client.get("/api/v1/workspace/review?page=2&limit=30").json()
    assert rev_page1["total"] == 34
    assert len(rev_page1["items"]) == 30
    assert len(rev_page2["items"]) == 4

    jobs_page1 = client.get("/api/v1/workspace/jobs?page=1&limit=30").json()
    jobs_page2 = client.get("/api/v1/workspace/jobs?page=2&limit=30").json()
    assert jobs_page1["total"] >= 33
    assert len(jobs_page1["items"]) == 30
    assert len(jobs_page2["items"]) >= 3

    # 4. Verify owner isolation & shared template review exclusion for a regular user
    client.post(
        "/api/v1/admin/users",
        json={"username": "member2", "password": PASSWORD, "display_name": "Member 2"},
    ).raise_for_status()
    login(client, "member2")

    assert client.get(f"/api/v1/speakers/{speaker_id}").status_code == 404
    member_rev = client.get("/api/v1/workspace/review").json()
    assert member_rev["total"] == 0
    member_docs = client.get("/api/v1/workspace/documents").json()
    assert member_docs["total"] == 0
    member_jobs = client.get("/api/v1/workspace/jobs").json()
    assert member_jobs["total"] == 0


def test_paginated_admin_and_resource_lists_preserve_legacy_and_ownership(client):
    """Pages search the complete collection, with stable order and owner boundaries."""
    mongo = client.app.state.mongo
    db = mongo.db
    owner = client.get("/api/v1/auth/me").json()["id"]
    m = meeting(client)
    stamp = "2026-11-06T04:00:00+00:00"
    db.jobs.insert_many(
        [
            {
                "_id": f"page-job-{i:04}",
                "owner_id": owner,
                "resource_type": "meeting",
                "resource_id": m["id"],
                "kind": "generate_minutes",
                "state": "succeeded",
                "stage": "Hoàn tất kiểm tra",
                "created_at": stamp,
            }
            for i in range(235)
        ]
    )
    for endpoint in ["/admin/jobs", "/workspace/jobs"]:
        first = client.get("/api/v1" + endpoint, params={"page": 1, "limit": 10}).json()
        second = client.get("/api/v1" + endpoint, params={"page": 2, "limit": 10}).json()
        assert first["total"] == second["total"] == 235
        assert len(first["items"]) == len(second["items"]) == 10
        assert not {row["id"] for row in first["items"]} & {row["id"] for row in second["items"]}
        assert client.get("/api/v1" + endpoint, params={"page": 1, "limit": 101}).status_code == 422
    assert isinstance(client.get("/api/v1/admin/jobs").json(), list)
    assert (
        client.get("/api/v1/workspace/jobs", params={"page": 1, "q": m["title"]}).json()["total"]
        == 235
    )
    assert (
        client.get("/api/v1/workspace/jobs", params={"page": 1, "q": "[.*]"}).json()["total"] == 0
    )
    db.audit_events.insert_many(
        [
            {
                "_id": f"page-audit-{i:04}",
                "owner_id": owner,
                "resource_id": "page-target",
                "action": "page_check",
                "created_at": stamp,
                "details": {},
            }
            for i in range(335)
        ]
    )
    audit = client.get(
        "/api/v1/admin/audit", params={"page": 34, "limit": 10, "q": "page-target"}
    ).json()
    assert audit["total"] == 335 and len(audit["items"]) == 5
    assert isinstance(client.get("/api/v1/admin/audit").json(), list)
    base = db.users.find_one({"_id": owner})
    db.users.insert_many(
        [
            {
                **base,
                "_id": f"page-user-{i:04}",
                "username": f"paged-user-{i:04}",
                "display_name": f"Paged user {i}",
                "role": "user",
            }
            for i in range(24)
        ]
    )
    users = client.get(
        "/api/v1/admin/users", params={"page": 3, "limit": 10, "q": "paged-user"}
    ).json()
    assert users["total"] == 24 and len(users["items"]) == 4
    db.templates.insert_many(
        [
            {
                "_id": f"page-template-{i:04}",
                "owner_id": owner,
                "name": f"Paged template {i}",
                "visibility": "shared" if i < 3 else "private",
                "state": "ready",
                "needs_review": False,
                "active_job": None,
                "trashed": False,
                "created_at": stamp,
            }
            for i in range(27)
        ]
    )
    db.speakers.insert_many(
        [
            {
                "_id": f"page-voice-{i:04}",
                "owner_id": owner,
                "name": f"Paged voice {i}",
                "sample_ids": [],
                "trashed": False,
                "created_at": stamp,
                "state": "ready",
            }
            for i in range(24)
        ]
    )
    for endpoint, expected in [("/templates", 27), ("/speakers", 24)]:
        response = client.get("/api/v1" + endpoint, params={"page": 2, "limit": 10}).json()
        assert response["total"] == expected and len(response["items"]) == 10
        assert isinstance(client.get("/api/v1" + endpoint).json(), list)
    client.post(
        "/api/v1/admin/users",
        json={"username": "pagingmember", "password": PASSWORD, "display_name": "Paging member"},
    ).raise_for_status()
    login(client, "pagingmember")
    assert client.get("/api/v1/admin/jobs?page=1").status_code == 403
    assert client.get("/api/v1/admin/audit?page=1").status_code == 403
    assert client.get("/api/v1/workspace/jobs?page=1").json()["total"] == 0
    assert client.get("/api/v1/templates?page=1").json()["total"] == 3
    assert client.get("/api/v1/speakers?page=1").json()["total"] == 0
