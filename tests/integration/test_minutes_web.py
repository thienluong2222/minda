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


def test_upload_template_and_download_minutes(web_client: tuple[TestClient, str, Path]) -> None:
    """Test uploading a Word template (.doc), extracting minutes, and downloading DOCX."""
    client, job_id, run_dir = web_client
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
