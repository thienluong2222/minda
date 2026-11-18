"""Integration tests for Web API minutes and template endpoints.

Specification: Section 5 (F4) of docs/PLAN_BIEU_MAU_BIEN_BAN_V1.md.
Gate F4: Sửa schema/value/transcript không gọi ASR; run cũ vẫn mở được; download file docx/zip.
"""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from meeting_pipeline.config import load_config
from meeting_pipeline.web.app import create_app

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"
TEMPLATES_DIR = FIXTURES_DIR / "templates"
AUDIO_RUN_DIR = (
    REPO_ROOT / "data" / "meetings" / "1" / "runs" / "a6e814e4-ea36-4cc9-8992-ba60b9341ea5"
)


@pytest.fixture
def web_client(tmp_path: Path) -> tuple[TestClient, str, Path]:
    """Create a FastAPI TestClient with an isolated demo job and run directory."""
    config = load_config(REPO_ROOT / "configs" / "default.yaml")
    config.paths.data_dir = tmp_path / "data"
    config.paths.data_dir.mkdir(parents=True, exist_ok=True)

    job_id = "test-job-minutes-123"
    job_run_dir = config.paths.data_dir / "meetings" / "1" / "runs" / job_id
    shutil.copytree(AUDIO_RUN_DIR, job_run_dir)
    # Ensure run is in pristine state without template
    shutil.rmtree(job_run_dir / "template", ignore_errors=True)
    shutil.rmtree(job_run_dir / "minutes", ignore_errors=True)
    if (job_run_dir / "exports" / "completed.docx").is_file():
        (job_run_dir / "exports" / "completed.docx").unlink()
    if (job_run_dir / "exports" / "completed_minutes.zip").is_file():
        (job_run_dir / "exports" / "completed_minutes.zip").unlink()

    # Create job file in demo_jobs
    demo_jobs_dir = config.paths.data_dir / "demo_jobs"
    demo_jobs_dir.mkdir(parents=True, exist_ok=True)
    job_record = {
        "job_id": job_id,
        "meeting_name": "Cuộc họp Ban Giám đốc Demo",
        "status": "succeeded",
        "source_paths": [],
        "source_names": ["mic_1.wav"],
        "run_dir": str(job_run_dir.resolve()),
        "created_at": "2026-10-03T10:00:00Z",
        "started_at": "2026-10-03T10:00:01Z",
        "completed_at": "2026-10-03T10:00:05Z",
    }
    (demo_jobs_dir / f"{job_id}.json").write_text(
        json.dumps(job_record, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    app = create_app(config)
    client = TestClient(app)
    return client, job_id, job_run_dir


def test_run_page_renders_without_template(web_client: tuple[TestClient, str, Path]) -> None:
    """Verify that existing audio runs without a template open normally (Gate F4 invariant)."""
    client, job_id, _ = web_client
    resp = client.get(f"/runs/{job_id}")
    assert resp.status_code == 200
    assert "Cuộc họp Ban Giám đốc Demo" in resp.text
    assert "Biên bản cuộc họp tự động" in resp.text
    assert "Tải lên mẫu biểu Word" in resp.text
    assert "minutes-mode" in resp.text
    assert "minutes-use-model" in resp.text
    assert "minutes-format-standard" in resp.text
    assert "hd05_2026" in resp.text


def test_minutes_model_status_does_not_load_weights(
    web_client: tuple[TestClient, str, Path],
) -> None:
    client, _, _ = web_client
    response = client.get("/api/minutes/models")
    assert response.status_code == 200
    assert response.json()["model_id"].endswith("Qwen3-4B-Instruct-2507-4bit")


def test_regenerate_requires_template_and_valid_options(
    web_client: tuple[TestClient, str, Path],
) -> None:
    client, job_id, _ = web_client
    response = client.post(
        f"/api/runs/{job_id}/minutes/regenerate", json={"mode": "general", "use_model": True}
    )
    assert response.status_code == 422
    response = client.post(f"/api/runs/{job_id}/minutes/regenerate", json={"mode": "invalid"})
    assert response.status_code == 422


def test_upload_template_and_download_minutes(web_client: tuple[TestClient, str, Path]) -> None:
    """Test uploading a Word template (.doc), extracting minutes, and downloading DOCX."""
    client, job_id, _run_dir = web_client
    template_path = TEMPLATES_DIR / "mau_bien_ban_hop_chung.doc"
    assert template_path.is_file()

    with template_path.open("rb") as f:
        file_bytes = f.read()

    # Upload template
    resp = client.post(
        f"/api/runs/{job_id}/template",
        files={
            "template": ("mau_bien_ban_hop_chung.doc", io.BytesIO(file_bytes), "application/msword")
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "success"
    assert data["fields_count"] > 0
    assert Path(data["completed_docx"]).is_file()
    assert Path(data["manifest_json"]).is_file()

    # Query minutes status
    resp_min = client.get(f"/api/runs/{job_id}/minutes")
    assert resp_min.status_code == 200
    min_data = resp_min.json()
    assert min_data["has_template"] is True
    assert len(min_data["facts"]) > 0
    assert min_data["manifest"] is not None

    # Test download completed docx
    resp_dl = client.get(f"/api/runs/{job_id}/minutes/download?format=docx")
    assert resp_dl.status_code == 200
    assert len(resp_dl.content) > 1000

    # Test download completed zip
    resp_zip = client.get(f"/api/runs/{job_id}/minutes/download?format=zip")
    assert resp_zip.status_code == 200
    assert len(resp_zip.content) > 1000


def test_edit_facts_and_transcript_without_asr(web_client: tuple[TestClient, str, Path]) -> None:
    """Test manual editing of facts and transcript without triggering ASR."""
    client, job_id, run_dir = web_client

    # 1. First process template
    template_path = TEMPLATES_DIR / "bien_ban_hop_chi_bo.docx"
    with template_path.open("rb") as f:
        client.post(
            f"/api/runs/{job_id}/template",
            files={
                "template": (
                    "bien_ban_hop_chi_bo.docx",
                    io.BytesIO(f.read()),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )

    # 2. Edit facts via POST /api/runs/{job_id}/minutes/facts
    resp_min = client.get(f"/api/runs/{job_id}/minutes")
    facts = resp_min.json()["facts"]
    assert len(facts) > 0

    # Update first fact value
    facts[0]["value"] = "Giá trị đã sửa tay qua Web API"
    facts[0]["status"] = "supported"
    facts[0]["user_edited"] = True

    resp_edit = client.post(
        f"/api/runs/{job_id}/minutes/facts",
        json={"facts": facts},
    )
    assert resp_edit.status_code == 200
    assert resp_edit.json()["status"] == "ok"

    # Verify updated completed.docx
    completed_docx = run_dir / "exports" / "completed.docx"
    assert completed_docx.is_file()

    # 3. Edit transcript via POST /api/runs/{job_id}/edit-transcript
    resp_trans = client.post(
        f"/api/runs/{job_id}/edit-transcript",
        json={"segment_index": 0, "new_text": "Phát biểu khai mạc đã được biên tập lại."},
    )
    assert resp_trans.status_code == 200
    assert resp_trans.json()["status"] == "ok"

    # Verify timeline.json updated
    timeline_data = json.loads((run_dir / "timeline.json").read_text(encoding="utf-8"))
    assert timeline_data["segments"][0]["text"] == "Phát biểu khai mạc đã được biên tập lại."
    assert timeline_data["segments"][0]["user_edited"] is True


def test_format_selection_persists_through_api_without_inference(
    web_client: tuple[TestClient, str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import meeting_pipeline.minutes.service as service

    client, job_id, run_dir = web_client
    with (TEMPLATES_DIR / "bien_ban_hop_chi_bo.docx").open("rb") as template:
        response = client.post(
            f"/api/runs/{job_id}/template",
            files={"template": ("meeting.docx", template)},
            data={
                "format_standard": "hd05_2026",
                "two_sided": "true",
                "document_metadata": json.dumps(
                    {"organization": "CHI BỘ A", "issue_date": "2026-10-15"}
                ),
            },
        )
    assert response.status_code == 200, response.text
    current = client.get(f"/api/runs/{job_id}/minutes").json()
    assert current["configuration"]["format_standard"] == "hd05_2026"
    assert current["formatting_report"]["two_sided"] is True
    facts = current["facts"]
    monkeypatch.setattr(service, "run_text_models", lambda *a, **k: pytest.fail("Unexpected LLM"))
    response = client.post(
        f"/api/runs/{job_id}/minutes/format", json={"format_standard": "nd30_2020"}
    )
    assert response.status_code == 200, response.text
    current = client.get(f"/api/runs/{job_id}/minutes").json()
    assert current["configuration"]["format_standard"] == "nd30_2020"
    assert current["facts"] == facts
    page = client.get(f"/runs/{job_id}")
    assert page.status_code == 200
    assert 'value="nd30_2020" selected' in page.text
    assert "minutes-formatting-report" in page.text
    assert (run_dir / "minutes/formatting_report.json").is_file()
    invalid = client.post(f"/api/runs/{job_id}/minutes/format", json={"format_standard": "other"})
    assert invalid.status_code == 422
    with (TEMPLATES_DIR / "bien_ban_hop_chi_bo.docx").open("rb") as template:
        invalid = client.post(
            f"/api/runs/{job_id}/template",
            files={"template": ("meeting.docx", template)},
            data={"document_metadata": "{invalid json"},
        )
    assert invalid.status_code == 422


def _create_regression_minutes(client, job_id):
    return client.post(
        f"/api/runs/{job_id}/template",
        files={
            "template": (
                "mau.docx",
                (TEMPLATES_DIR / "bien_ban_hop_chi_bo.docx").read_bytes(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        data={"format_standard": "hd05_2026"},
    )


def test_busy_schema_has_no_partial_writes(web_client):
    from meeting_pipeline.minutes.service import GENERATION_LOCK

    client, job_id, run = web_client
    assert _create_regression_minutes(client, job_id).status_code == 200
    paths = [
        run / "template/schema.json",
        run / "minutes/facts.json",
        run / "exports/completed.docx",
    ]
    before = [p.read_bytes() for p in paths]
    fields = json.loads(paths[0].read_text())["fields"]
    GENERATION_LOCK.acquire()
    try:
        response = client.post(f"/api/runs/{job_id}/template/schema", json={"fields": fields})
    finally:
        GENERATION_LOCK.release()
    assert response.status_code == 503
    assert [p.read_bytes() for p in paths] == before


def test_transcript_edit_keeps_profile_manifest_and_zip_consistent(web_client):
    import hashlib
    import zipfile

    from docx import Document

    client, job_id, run = web_client
    assert _create_regression_minutes(client, job_id).status_code == 200
    rows = json.loads((run / "timeline.json").read_text())["segments"]
    result = client.post(
        f"/api/runs/{job_id}/edit-transcript",
        json={"segment_index": 0, "new_text": rows[0]["text"] + "."},
    )
    assert result.status_code == 200
    output = (run / "exports/completed.docx").read_bytes()
    assert "Minutes Body" in Document(run / "exports/completed.docx").styles
    assert abs(Document(run / "exports/completed.docx").sections[0].page_width.mm - 210) < 0.1
    assert (
        hashlib.sha256(output).hexdigest()
        == json.loads((run / "minutes/manifest.json").read_text())["completed_docx_sha256"]
    )
    with zipfile.ZipFile(run / "exports/completed_minutes.zip") as archive:
        assert archive.read("completed.docx") == output


def test_rename_marks_document_stale(web_client):
    client, job_id, run = web_client
    assert _create_regression_minutes(client, job_id).status_code == 200
    timeline_path = run / "timeline.json"
    timeline = json.loads(timeline_path.read_text())
    timeline["segments"][0].update(
        meeting_speaker_id="speaker_001",
        speaker_label="Minh",
        speaker_status="identified",
        speaker_id="person-001",
    )
    timeline_path.write_text(json.dumps(timeline))
    speakers = client.get(f"/api/runs/{job_id}/speakers").json()
    target = next(s for s in speakers if s["meeting_speaker_id"])
    result = client.post(
        f"/api/runs/{job_id}/rename-speaker",
        json={"meeting_speaker_id": target["meeting_speaker_id"], "new_label": "Tên đã kiểm tra"},
    )
    assert result.status_code == 200
    assert json.loads((run / "minutes/model_report.json").read_text())[
        "stale_since_transcript_edit"
    ]


def test_schema_render_failure_rolls_back_schema_facts_and_audit(web_client, monkeypatch):
    from meeting_pipeline.minutes.service import MinutesService

    client, job_id, run = web_client
    assert _create_regression_minutes(client, job_id).status_code == 200
    paths = [
        run / "template/schema.json",
        run / "minutes/facts.json",
        run / "exports/completed.docx",
    ]
    before = [p.read_bytes() for p in paths]

    def fail(*args, **kwargs):
        raise RuntimeError("simulated render failure")

    monkeypatch.setattr(MinutesService, "_update_facts_and_re_render", fail)
    result = client.post(
        f"/api/runs/{job_id}/template/schema",
        json={"fields": json.loads(paths[0].read_text())["fields"]},
    )
    assert result.status_code == 400
    assert [p.read_bytes() for p in paths] == before
    assert not (run / "template/schema_review.json").exists()
