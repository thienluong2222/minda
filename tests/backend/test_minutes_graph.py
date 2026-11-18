"""Real isolated MongoDB checks: policy, frozen inputs, access and confirmed feedback."""

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from meeting_backend.core.settings import Settings
from meeting_backend.integrations.minutes_pipeline import materialize_transcript
from meeting_backend.main import create_app
from meeting_backend.modules.minutes.graph_store import persist_graph
from meeting_backend.modules.minutes.outline_store import persist_outline
from meeting_backend.modules.transcripts.service import create_version
from meeting_pipeline.minutes.graph_builder import build_graph, fallback_event
from meeting_pipeline.minutes.graph_inputs import make_graph_units

PASSWORD = "graph-test-password-12345"


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        mongo_database="meeting_app_graph_test_" + uuid4().hex,
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


def ready_meeting(client):
    m = client.post("/api/v1/meetings", json={"title": "Họp tiến độ", "location": "B201"}).json()
    mongo = client.app.state.mongo
    raw = mongo.db.meetings.find_one({"_id": m["id"]})
    transcript = create_version(
        mongo,
        raw,
        [
            {
                "text": "An đề nghị hạn 15/11.",
                "speaker_label": "An",
                "start_sec": 0,
                "end_sec": 4,
                "asr_status": "transcribed",
            }
        ],
        reason="test",
    )
    mongo.db.meetings.update_one(
        {"_id": m["id"]},
        {"$set": {"active_transcript_id": transcript["_id"], "state": "transcript_ready"}},
    )
    template_id = uuid4().hex
    mongo.db.templates.insert_one(
        {
            "_id": template_id,
            "owner_id": raw["owner_id"],
            "state": "ready",
            "trashed": False,
            "active_version_id": "template-v1",
            "needs_review": False,
        }
    )
    return mongo.db.meetings.find_one({"_id": m["id"]}), template_id


def test_old_preset_gets_defaults_and_new_jobs_pin_policy_and_input(client, tmp_path):
    mongo = client.app.state.mongo
    mongo.db.settings.insert_one({"_id": "processing_preset", "revision": 1, "use_model": False})
    preset = client.get("/api/v1/admin/preset").json()
    assert preset["minutes_graph_enabled"] is True
    assert preset["minutes_style_learning_enabled"] is True
    m, template = ready_meeting(client)
    source_turn = mongo.db.transcript_segments.find_one({"version_id": m["active_transcript_id"]})
    response = client.post(
        f"/api/v1/meetings/{m['_id']}/minutes/generate",
        json={
            "revision": m["revision"],
            "template_id": template,
            "options": {"use_model": False, "graph_enabled": False},
            "agenda": ["Tiến độ"],
            "turn_sessions": {source_turn["_id"]: "Phiên 1"},
        },
    )
    response.raise_for_status()
    job = mongo.db.jobs.find_one({"_id": response.json()["id"]})
    assert job["payload"]["options"]["graph_enabled"] is True
    assert job["payload"]["options"]["use_model"] is True
    assert job["payload"]["metadata_snapshot"]["agenda"] == ["Tiến độ"]
    assert job["payload"]["metadata_snapshot"]["turn_sessions"] == {source_turn["_id"]: "Phiên 1"}
    mongo.db.transcript_segments.update_many(
        {"version_id": m["active_transcript_id"]}, {"$set": {"text": "Đã đổi ngoài luồng."}}
    )
    mongo.db.settings.update_one(
        {"_id": "processing_preset"}, {"$set": {"minutes_graph_enabled": False}}
    )
    run = tmp_path / "frozen"
    run.mkdir()
    materialize_transcript(SimpleNamespace(mongo=mongo, job=job), m, run)
    assert (
        json.loads((run / "timeline.json").read_text())["segments"][0]["text"]
        == "An đề nghị hạn 15/11."
    )
    client.post(f"/api/v1/jobs/{job['_id']}/cancel").raise_for_status()
    current = mongo.db.meetings.find_one({"_id": m["_id"]})
    response = client.post(
        f"/api/v1/meetings/{m['_id']}/minutes/generate",
        json={
            "revision": current["revision"],
            "template_id": template,
            "options": {"use_model": False},
        },
    )
    response.raise_for_status()
    second = mongo.db.jobs.find_one({"_id": response.json()["id"]})
    assert second["payload"]["options"]["graph_enabled"] is False
    assert second["payload"]["options"]["use_model"] is False


def test_outline_edit_pins_plan_and_validates_items_before_queueing(client, tmp_path):
    from meeting_pipeline.minutes.evidence_retrieval import IndexedTurn
    from meeting_pipeline.minutes.graph_plan import ContentPlan
    from meeting_pipeline.minutes.graph_writer import plan_sections

    mongo = client.app.state.mongo
    meeting, _ = ready_meeting(client)
    units, _ = make_graph_units(
        [
            IndexedTurn(
                turn_id="t",
                speaker_id="an",
                speaker_label="An",
                start_sec=0.0,
                end_sec=4.0,
                text="An gửi báo cáo tuần.",
                tokens=[],
                source_id="s",
                clip_path=None,
                asr_status="transcribed",
                needs_review=False,
                confidence=None,
            )
        ]
    )
    graph = build_graph(
        meeting["_id"],
        units,
        [fallback_event(units[0])],
        {"titles": ["Báo cáo"], "primary": [0], "membership": [[1.0]], "cluster_count": 1},
        [],
        metadata={"transcript_version_id": meeting["active_transcript_id"]},
    )
    sections, ledger = plan_sections(graph)
    plan = ContentPlan(
        graph_id=graph.graph_id,
        transcript_version_id=meeting["active_transcript_id"],
        phase="written",
        sections=sections,
        ledger=ledger,
    )
    plan.seal()
    output = tmp_path / "stored-doc" / "minutes"
    output.mkdir(parents=True)
    (output / "content_plan.json").write_text(plan.model_dump_json())
    (output / "meeting_graph.json").write_text(graph.model_dump_json())
    version = {
        "_id": "stored",
        "meeting_id": meeting["_id"],
        "run_path": str(output.parent),
        "graph_id": graph.graph_id,
        "transcript_version_id": meeting["active_transcript_id"],
        "input_content_revision": meeting["content_revision"],
        "outline": persist_outline(mongo, meeting, "stored", plan.model_dump()),
    }
    mongo.db.minutes_versions.insert_one(version)
    mongo.db.meetings.update_one({"_id": meeting["_id"]}, {"$set": {"active_minutes_id": "stored"}})

    url = f"/api/v1/meetings/{meeting['_id']}/minutes/outline"
    draft = client.get(url + "/draft").json()
    assert draft["plan_id"] == plan.plan_id
    payload = {
        **draft,
        "sections": [
            {
                "section_id": section["section_id"],
                "title": "Tiến độ",
                "items": [
                    {"item_id": item["item_id"], "priority": "required", "included": True}
                    for item in section["items"]
                ],
            }
            for section in draft["sections"]
        ],
    }
    assert client.patch(url, json={**payload, "plan_id": "older"}).status_code == 409
    assert client.patch(url, json={**payload, "sections": []}).status_code == 422
    response = client.patch(url, json=payload)
    assert response.status_code == 202
    job = mongo.db.jobs.find_one({"_id": response.json()["id"]})
    assert job["kind"] == "revise_minutes_outline"
    assert job["payload"]["version_id"] == "stored"
    assert job["payload"]["plan_id"] == plan.plan_id
    client.post(f"/api/v1/jobs/{job['_id']}/cancel").raise_for_status()


def test_graph_api_paginates_and_scopes_ownership(client):
    from meeting_pipeline.minutes.evidence_retrieval import IndexedTurn

    mongo = client.app.state.mongo
    m, _ = ready_meeting(client)
    turn = IndexedTurn(
        turn_id="t",
        speaker_label="An",
        speaker_id="an",
        start_sec=0,
        end_sec=2,
        text="An rà hồ sơ.",
        tokens=[],
        source_id="s",
        clip_path=None,
        asr_status="transcribed",
        needs_review=False,
        confidence=None,
    )
    units, _ = make_graph_units([turn])
    graph = build_graph(
        m["_id"],
        units,
        [fallback_event(units[0])],
        {"cluster_count": 1, "primary": [0], "membership": [[1.0]], "titles": ["Hồ sơ"]},
        [],
    )
    persist_graph(mongo, m, graph.model_dump())
    persist_graph(mongo, m, graph.model_dump())
    version_id = uuid4().hex
    mongo.db.minutes_versions.insert_one(
        {
            "_id": version_id,
            "meeting_id": m["_id"],
            "owner_id": m["owner_id"],
            "graph_id": graph.graph_id,
        }
    )
    mongo.db.meetings.update_one({"_id": m["_id"]}, {"$set": {"active_minutes_id": version_id}})
    base = f"/api/v1/meetings/{m['_id']}/minutes/graph"
    assert client.get(base).json()["node_count"] == len(graph.nodes)
    page = client.get(base + "/nodes", params={"limit": 2}).json()
    assert len(page["items"]) == 2 and page["total"] == len(graph.nodes)
    assert client.get(base + "/edges", params={"node_id": units[0].unit_id}).json()["total"] > 0
    overview = client.get(base + "/view").json()
    assert "topic:0" in {node["node_id"] for node in overview["nodes"]}
    detail = client.get(base + "/view", params={"node_id": "topic:0"}).json()
    assert graph.events[0].event_id in {node["node_id"] for node in detail["nodes"]}
    evidence = next(node for node in detail["nodes"] if node["kind"] == "evidence")
    assert evidence["attributes"]["speaker"] == "An"
    assert evidence["attributes"]["end_sec"] == 2
    assert evidence["attributes"]["sources"][0]["text"] == "An rà hồ sơ."
    assert client.get(base + "/nodes", params={"q": "HỒ SƠ", "kind": "topic"}).json()["total"] == 1
    assert client.get(base + "/nodes", params={"q": ".*"}).json()["total"] == 0
    assert client.get(base + "/view", params={"node_id": "missing"}).status_code == 404
    from meeting_pipeline.minutes.graph_writer import plan_sections

    sections, ledger = plan_sections(graph)
    plan = {
        "schema_version": "2.0",
        "sections": [s.model_dump() for s in sections],
        "ledger": ledger,
    }
    metadata = persist_outline(mongo, m, version_id, plan)
    persist_outline(mongo, m, version_id, plan)
    mongo.db.minutes_versions.update_one({"_id": version_id}, {"$set": {"outline": metadata}})
    outline_url = f"/api/v1/meetings/{m['_id']}/minutes/outline"
    outline = client.get(outline_url).json()
    assert outline["available"] is True
    assert outline["items"][0]["items"][0]["evidence_ids"] == [units[0].unit_id]
    assert (
        client.get(outline_url + "/items", params={"section_id": sections[0].section_id}).json()[
            "total"
        ]
        == 1
    )
    readable = client.get(base + "/view", params={"mode": "content", "node_id": "topic:0"}).json()
    assert all(
        node["kind"] not in {"evidence", "person", "episode", "session"}
        for node in readable["nodes"]
    )
    assert any(edge.get("projection") and not edge["asserted"] for edge in readable["edges"])
    assert client.get(base + "/view", params={"mode": "unknown"}).status_code == 422
    admin_preset = client.get("/api/v1/admin/preset").json()
    client.post(
        "/api/v1/admin/users",
        json={"username": "reader", "display_name": "Reader", "password": PASSWORD, "role": "user"},
    ).raise_for_status()
    login(client, "reader")
    assert client.get(base).status_code == 404
    assert client.get(base + "/view").status_code == 404
    assert client.get(base + "/nodes", params={"q": "An"}).status_code == 404
    assert client.get(outline_url).status_code == 404
    assert (
        client.get(
            outline_url + "/items", params={"section_id": sections[0].section_id}
        ).status_code
        == 404
    )
    assert client.put("/api/v1/admin/preset", json=admin_preset).status_code == 403


def test_large_graph_is_bounded_paginates_and_pins_version(client):
    mongo = client.app.state.mongo
    m, _ = ready_meeting(client)
    nodes = [{"node_id": "topic:0", "kind": "topic", "label": "Tiến độ", "attributes": {}}]
    edges = []
    for i in range(240):
        nodes.extend(
            [
                {"node_id": f"u{i}", "kind": "evidence", "label": f"Ý kiến {i}", "attributes": {}},
                {"node_id": f"e{i}", "kind": "task", "label": f"Công việc {i}", "attributes": {}},
            ]
        )
        edges.extend(
            [
                {"source": f"u{i}", "target": "topic:0", "kind": "about"},
                {"source": f"e{i}", "target": f"u{i}", "kind": "evidenced_by"},
            ]
        )
    graph = {
        "graph_id": "large",
        "input_sha256": "test",
        "schema_version": "1",
        "nodes": nodes,
        "edges": edges,
    }
    persist_graph(mongo, m, graph)
    mongo.db.minutes_versions.insert_many(
        [
            {"_id": "large-version", "meeting_id": m["_id"], "graph_id": "large"},
            {"_id": "legacy-version", "meeting_id": m["_id"]},
        ]
    )
    mongo.db.meetings.update_one(
        {"_id": m["_id"]}, {"$set": {"active_minutes_id": "legacy-version"}}
    )
    base = f"/api/v1/meetings/{m['_id']}/minutes/graph/view"
    assert client.get(base).status_code == 404
    seen = set()
    for page in range(1, 7):
        result = client.get(
            base,
            params={
                "version_id": "large-version",
                "node_id": "topic:0",
                "page": page,
            },
        )
        result.raise_for_status()
        value = result.json()
        ids = {node["node_id"] for node in value["nodes"]}
        assert len(ids) <= 200 and len(value["edges"]) <= 600
        assert all(e["source"] in ids and e["target"] in ids for e in value["edges"])
        assert value["total"] == 240
        assert value["has_more"] is (page < 6)
        seen.update(node_id for node_id in ids if node_id.startswith("u"))
        for node_id in ids:
            if node_id.startswith("u"):
                assert "e" + node_id[1:] in ids
    assert len(seen) == 240
    dense = client.get(
        base,
        params={
            "version_id": "large-version",
            "node_id": "topic:0",
            "limit": 100,
        },
    ).json()
    assert dense["truncated"] is True and len(dense["nodes"]) == 200
    visible = {node["node_id"] for node in dense["nodes"]}
    assert all(e["source"] in visible and e["target"] in visible for e in dense["edges"])


def test_outline_pagination_and_history_do_not_mix_versions(client):
    mongo = client.app.state.mongo
    meeting, _ = ready_meeting(client)
    for version_id in ("outline-old", "outline-new"):
        plan = {
            "schema_version": "2.0",
            "sections": [
                {
                    "section_id": "section_0",
                    "title": "Tiến độ",
                    "outline": [
                        {
                            "item_id": f"claim-{i}",
                            "claim_ids": [f"claim-{i}"],
                            "evidence_ids": [f"unit-{i}"],
                            "role": "task",
                            "text": f"{version_id}: {i}",
                        }
                        for i in range(72)
                    ],
                }
            ],
        }
        metadata = persist_outline(mongo, meeting, version_id, plan)
        mongo.db.minutes_versions.insert_one(
            {"_id": version_id, "meeting_id": meeting["_id"], "outline": metadata}
        )
    mongo.db.meetings.update_one(
        {"_id": meeting["_id"]}, {"$set": {"active_minutes_id": "outline-new"}}
    )
    base = f"/api/v1/meetings/{meeting['_id']}/minutes/outline"
    active = client.get(base).json()
    assert len(active["items"][0]["items"]) == 6
    assert active["items"][0]["items"][0]["text"] == "outline-new: 0"
    old = client.get(base, params={"version_id": "outline-old"}).json()
    assert old["items"][0]["items"][0]["text"] == "outline-old: 0"
    last = client.get(
        base + "/items", params={"section_id": "section_0", "page": 4, "limit": 20}
    ).json()
    assert last["total"] == 72 and len(last["items"]) == 12
    assert last["items"][0]["text"] == "outline-new: 60"
    other, _ = ready_meeting(client)
    response = client.get(
        f"/api/v1/meetings/{other['_id']}/minutes/outline", params={"version_id": "outline-old"}
    )
    assert response.status_code == 404


def test_only_reviewed_narrative_edits_teach_style_and_repeat_review_is_idempotent(client):
    mongo = client.app.state.mongo
    for index in range(2):
        m, _ = ready_meeting(client)
        parent_id, version_id = uuid4().hex, uuid4().hex
        claim_text = "An sẽ rà hồ sơ trước 17/6."
        output = mongo.settings.data_dir / parent_id / "minutes"
        output.mkdir(parents=True)
        (output / "content_plan.json").write_text(
            json.dumps(
                {
                    "schema_version": "3.0",
                    "sections": [
                        {
                            "paragraphs": [
                                {
                                    "verification": "checked",
                                    "claim_ids": ["c0"],
                                    "text": claim_text,
                                    "alignments": [
                                        {
                                            "claim_id": "c0",
                                            "start_char": 0,
                                            "end_char": len(claim_text),
                                        }
                                    ],
                                }
                            ]
                        }
                    ],
                }
            )
        )
        common = {
            "owner_id": m["owner_id"],
            "meeting_id": m["_id"],
            "input_content_revision": 0,
            "schema": {"fields": [{"field_id": "body", "semantic_type": "discussion_summary"}]},
            "topics": {"units": [{"speaker": "An"}]},
        }
        mongo.db.minutes_versions.insert_one(
            {
                **common,
                "_id": parent_id,
                "run_path": str(output.parent),
                "facts": [
                    {
                        "field_id": "body",
                        "value": "1. " + claim_text,
                    }
                ],
            }
        )
        mongo.db.minutes_versions.insert_one(
            {
                **common,
                "_id": version_id,
                "parent_id": parent_id,
                "reason": "edit_facts",
                "facts": [
                    {
                        "field_id": "body",
                        "value": claim_text,
                        "status": "needs_review",
                        "previous_edit": None,
                    }
                ],
            }
        )
        mongo.db.meetings.update_one(
            {"_id": m["_id"]}, {"$set": {"active_minutes_id": version_id, "minutes_stale": False}}
        )
        url = f"/api/v1/meetings/{m['_id']}/minutes/review"
        client.post(url, json={"revision": m["revision"]}).raise_for_status()
        record = mongo.db.style_profiles.find_one({"_id": m["owner_id"]})
        rules = [r for r in record["profile"]["rules"] if r["rule_id"].startswith("learned_")]
        assert all(r["support_count"] == index + 1 for r in rules)
        updated = mongo.db.meetings.find_one({"_id": m["_id"]})
        client.post(url, json={"revision": updated["revision"]}).raise_for_status()
        assert (
            mongo.db.style_profiles.find_one({"_id": m["owner_id"]})["profile"] == record["profile"]
        )
    assert any(r["active"] for r in rules)


def test_reformat_roundtrip_preserves_graph_engine_in_saved_options(client):
    mongo = client.app.state.mongo
    m, _ = ready_meeting(client)
    version_id = uuid4().hex
    mongo.db.minutes_versions.insert_one(
        {
            "_id": version_id,
            "meeting_id": m["_id"],
            "owner_id": m["owner_id"],
            "options": {"graph_enabled": True},
        }
    )
    mongo.db.meetings.update_one({"_id": m["_id"]}, {"$set": {"active_minutes_id": version_id}})
    response = client.post(
        f"/api/v1/meetings/{m['_id']}/minutes/format",
        json={
            "revision": m["revision"],
            "options": {"graph_enabled": False},
        },
    )
    response.raise_for_status()
    job = mongo.db.jobs.find_one({"_id": response.json()["id"]})
    assert job["payload"]["options"]["graph_enabled"] is True
