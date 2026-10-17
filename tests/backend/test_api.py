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
