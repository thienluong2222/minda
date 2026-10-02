from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient

from meeting_pipeline.config import load_config
from meeting_pipeline.web.app import create_app


def _client(tmp_path: Path) -> TestClient:
    config = load_config(Path("configs/default.yaml"))
    config.paths.data_dir = tmp_path / "data"
    config.paths.model_cache_dir = tmp_path / "models"
    return TestClient(create_app(config))


def _wav() -> bytes:
    buffer = io.BytesIO()
    sf.write(buffer, np.zeros(16000, dtype=np.float32), 16000, format="WAV")
    return buffer.getvalue()


def _fixture_run(tmp_path: Path, version: str) -> Path:
    run = tmp_path / f"run-{version}"
    for directory in ("aligned", "clips/evidence", "exports"):
        (run / directory).mkdir(parents=True)
    for relative in (
        "aligned/source-1.wav",
        "aligned/source-2.wav",
        "aligned/combined.wav",
        "clips/evidence/a.wav",
        "clips/evidence/b.wav",
    ):
        (run / relative).write_bytes(_wav())
    for extension in ("json", "csv", "txt", "zip"):
        (run / "exports" / f"result.{extension}").write_bytes(extension.encode())
    (run / "coverage.json").write_text(
        json.dumps(
            {
                "schema_version": version,
                "reference_source_id": "source-1",
                "sources": [
                    {
                        "source_id": "source-1",
                        "original_name": "máy <script>1</script>.wav",
                        "duration_sec": 12.5,
                        "synchronization": {
                            "offset_sec": 0.0,
                            "drift_ppm": 0.0,
                            "residual_ms": 0.0,
                        },
                    },
                    {
                        "source_id": "source-2",
                        "original_name": "máy 2.wav",
                        "duration_sec": 12.1,
                        "synchronization": {
                            "offset_sec": -0.12,
                            "drift_ppm": 2.0,
                            "residual_ms": 8.5,
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    segment: dict[str, object] = {
        "start_sec": 1.0,
        "end_sec": 3.0,
        "speaker_label": "Speaker 1",
        "speaker_status": "unknown",
        "speaker_match_score": 0.31,
        "speaker_top_candidates": [{"speaker_id": "profile-1", "cosine_score": 0.27}],
        "identity_decision_reason": "enrollment_rejected: below_threshold",
        "selected_source_id": "source-2",
        "text": "xin <script>alert(1)</script> chào",
        "transcript_confidence": 0.72,
        "needs_review": True,
        "evidence_clip_artifact_id": "clips/evidence/b.wav",
    }
    if version == "2.0":
        segment.update(
            fusion_method="F5_RULE_WEIGHTED",
            source_evidence=[
                {
                    "source_id": "source-1",
                    "selection_weight": 0.25,
                    "identity_weight": 0.7,
                    "candidate_scores": {
                        "transcript": "xin chào",
                        "audio_quality_score": 0.62,
                        "transcript_quality_score": 0.4,
                        "asr_confidence": 0.54,
                        "word_agreement": 0.5,
                    },
                    "raw_quality_features": {
                        "snr_est": 12.4,
                        "rms": 0.034,
                        "clipping_ratio": 0.02,
                        "dropout_ratio": 0.05,
                    },
                    "evidence_clip_artifact_id": "clips/evidence/a.wav",
                },
                {
                    "source_id": "source-2",
                    "selection_weight": 0.75,
                    "identity_weight": 0.3,
                    "candidate_scores": {
                        "transcript": "xin chào bạn",
                        "audio_quality_score": 0.84,
                        "transcript_quality_score": 0.9,
                        "asr_confidence": 0.87,
                        "word_agreement": 0.75,
                    },
                    "raw_quality_features": {
                        "snr_est": 21.3,
                        "rms": 0.08,
                        "clipping_ratio": 0.0,
                        "dropout_ratio": 0.01,
                    },
                    "evidence_clip_artifact_id": "clips/evidence/b.wav",
                },
            ],
            provenance={
                "word_provenance": [
                    {
                        "output_word": "xin",
                        "confidence": 0.81,
                        "supporting_sources": ["source-1", "source-2"],
                        "representative_source_id": "source-2",
                        "source_scores": {"source-1": 0.4, "source-2": 0.9},
                    }
                ]
            },
        )
    (run / "timeline.json").write_text(
        json.dumps({"schema_version": version, "segments": [segment]}), encoding="utf-8"
    )
    if version == "2.0":
        (run / "manifest.json").write_text(
            json.dumps(
                {
                    "fusion_method_requested": "F6_LEARNED",
                    "fusion_method_used": "F5_RULE_WEIGHTED",
                    "identity_method_used": "mfcc_knn",
                    "identity_threshold": 0.25,
                    "identity_margin": 0.05,
                    "warnings": ["F6 chưa được huấn luyện"],
                }
            ),
            encoding="utf-8",
        )
    return run


def _job(client: TestClient, run_dir: Path, status: str = "succeeded") -> None:
    client.app.state.demo_jobs.write(
        {
            "job_id": "demo-1",
            "meeting_name": "Họp & nghiên cứu",
            "status": status,
            "created_at": "2026-09-24T00:00:00+00:00",
            "run_dir": str(run_dir),
            "error": "Lỗi <script>test</script>" if status == "failed" else None,
        }
    )


def test_form_methods_profiles_and_upload(tmp_path: Path) -> None:
    client = _client(tmp_path)
    store = client.app.state.demo_jobs
    store.speakers.root.joinpath("person-1").mkdir(parents=True)
    (store.speakers.root / "person-1" / "profile.json").write_text(
        json.dumps(
            {
                "speaker_id": "person-1",
                "display_name": "An <b>",
                "sample_count": 2,
                "total_seconds": 7.0,
            }
        ),
        encoding="utf-8",
    )
    page = client.get("/")
    assert page.status_code == 200
    assert "Đăng ký mẫu giọng" in page.text
    assert "F5 ·" in page.text
    assert "MFCC + KNN" in page.text
    assert "An &lt;b&gt;" in page.text
    assert client.get("/static/demo.css").status_code == 200
    assert client.get("/static/demo.js").status_code == 200

    store.execute = lambda _job_id: None
    response = client.post(
        "/api/runs",
        data={
            "meeting_name": "Buổi demo",
            "identity_method": "mfcc_knn",
            "fusion_method": "F3_ROVER",
            "participant_ids": "person-1",
        },
        files=[
            ("sources", ("phone-a.wav", _wav(), "audio/wav")),
            ("sources", ("phone-b.wav", _wav(), "audio/wav")),
        ],
    )
    assert response.status_code == 202
    job = store.read(response.json()["job_id"])
    assert job["source_names"] == ["01-phone-a.wav", "02-phone-b.wav"]
    assert job["identity_method"] == "mfcc_knn"
    assert job["fusion_method"] == "F3_ROVER"
    assert job["participant_ids"] == ["person-1"]


def test_enrollment_upload(tmp_path: Path) -> None:
    client = _client(tmp_path)
    store = client.app.state.demo_jobs

    def fake_enroll(display_name: str, samples: list[Path]) -> dict[str, object]:
        assert display_name == "Lan"
        assert len(samples) == 2
        assert all(path.is_file() for path in samples)
        return {"speaker_id": "lan", "display_name": display_name, "sample_count": 2}

    store.speakers.enroll = fake_enroll
    response = client.post(
        "/api/speakers",
        data={"display_name": "Lan"},
        files=[
            ("samples", ("lan-1.wav", _wav(), "audio/wav")),
            ("samples", ("lan-2.wav", _wav(), "audio/wav")),
        ],
    )
    assert response.status_code == 200
    assert response.json()["sample_count"] == 2
    assert (
        client.post(
            "/api/speakers",
            data={"display_name": " "},
            files=[("samples", ("lan.wav", _wav(), "audio/wav"))],
        ).status_code
        == 400
    )


def test_status_error_and_invalid_upload(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _job(client, tmp_path, "running")
    pending = client.get("/runs/demo-1")
    assert pending.status_code == 200
    assert "Đang phân tích" in pending.text
    _job(client, tmp_path, "failed")
    failed = client.get("/runs/demo-1")
    assert "Không thể hoàn tất" in failed.text
    assert "&lt;script&gt;" in failed.text
    assert "<script>test</script>" not in failed.text
    assert (
        client.post(
            "/api/runs",
            data={"meeting_name": "   "},
            files=[("sources", ("bad.wav", b"bad", "audio/wav"))],
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/runs",
            data={"meeting_name": "Demo"},
            files=[("sources", ("bad.wav", b"bad", "audio/wav"))],
        ).status_code
        == 400
    )


def test_schema_2_result_evidence_audio_and_export(tmp_path: Path) -> None:
    client = _client(tmp_path)
    run = _fixture_run(tmp_path, "2.0")
    _job(client, run)
    page = client.get("/runs/demo-1")
    assert page.status_code == 200
    for text in (
        "F6_LEARNED",
        "F5_RULE_WEIGHTED",
        "đã chuyển sang",
        "Trọng số chất lượng transcript ở cấp đoạn",
        "Trọng số nguồn nhận diện",
        "Theo từng từ",
        "0.25",
        "0.75",
        "12.4 dB",
        "21.3 dB",
        "8.5 ms",
        "Speaker 1",
        "profile-1",
    ):
        assert text in page.text
    assert "máy &lt;script&gt;1&lt;/script&gt;.wav" in page.text
    assert "xin &lt;script&gt;alert(1)&lt;/script&gt; chào" in page.text
    assert "<script>alert(1)</script>" not in page.text
    assert "tỷ lệ số từ" in page.text
    assert client.get("/api/runs/demo-1/timeline").status_code == 200
    for extension in ("json", "csv", "txt", "zip"):
        assert (
            client.get(f"/api/runs/demo-1/export?format={extension}").content == extension.encode()
        )
    assert client.get("/api/runs/demo-1/files/clips/evidence/a.wav").status_code == 200
    assert client.get("/api/runs/demo-1/files/aligned/source-2.wav").status_code == 200
    assert "combined.wav" in page.text
    assert client.get("/api/runs/demo-1/files/aligned/combined.wav").status_code == 200
    assert client.get("/api/runs/demo-1/files/../../outside").status_code == 404


def test_skipped_overlap_shows_original_audio_without_claiming_a_transcript(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    run = _fixture_run(tmp_path, "2.0")
    original_paths = [f"clips/original/turn_0000/source-{index}.wav" for index in (1, 2)]
    for relative_path in original_paths:
        path = run / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_wav())
    timeline_path = run / "timeline.json"
    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    timeline["segments"][0].update(
        text="",
        asr_status="not_run",
        speaker_count=2,
        overlap_group_id="overlap-1",
        source_evidence=[],
        original_clip_artifact_ids=original_paths,
        evidence_clip_artifact_id=original_paths[0],
    )
    timeline_path.write_text(json.dumps(timeline), encoding="utf-8")
    _job(client, run)

    page = client.get("/runs/demo-1")
    assert page.status_code == 200
    assert "Đoạn nói chồng tạm thời chưa được chép lời" in page.text
    assert "Âm thanh gốc từng nguồn" in page.text
    assert "Run schema 2.0 chưa lưu transcript" not in page.text
    for relative_path in original_paths:
        assert relative_path in page.text


def test_schema_1_result_explains_missing_detail(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _job(client, _fixture_run(tmp_path, "1.0"))
    page = client.get("/runs/demo-1")
    assert page.status_code == 200
    assert "Run schema 1.0 chưa lưu transcript" in page.text
    assert "Run cũ không lưu phương pháp fusion" in page.text
    assert "Chưa có dữ liệu" in page.text


def test_running_job_is_failed_after_restart(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    job_dir = data_dir / "demo_jobs"
    job_dir.mkdir(parents=True)
    (job_dir / "stale.json").write_text(
        json.dumps({"job_id": "stale", "meeting_name": "Stale", "status": "running"}),
        encoding="utf-8",
    )
    config = load_config(Path("configs/default.yaml"))
    config.paths.data_dir = data_dir
    client = TestClient(create_app(config))
    assert client.get("/api/runs/stale").json()["status"] == "failed"


def test_get_meeting_speakers_and_rename_label(tmp_path: Path) -> None:
    client = _client(tmp_path)
    run = _fixture_run(tmp_path, "2.0")
    timeline_path = run / "timeline.json"
    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    timeline["segments"][0].update(
        meeting_speaker_id="ms-0001",
        speaker_label="Người lạ 1",
        speaker_status="anonymous",
    )
    timeline_path.write_text(json.dumps(timeline), encoding="utf-8")
    _job(client, run)

    # 1. GET /api/runs/demo-1/speakers
    res = client.get("/api/runs/demo-1/speakers")
    assert res.status_code == 200
    speakers = res.json()
    assert len(speakers) == 1
    assert speakers[0]["meeting_speaker_id"] == "ms-0001"
    assert speakers[0]["speaker_label"] == "Người lạ 1"
    assert speakers[0]["speaker_status"] == "anonymous"

    # 2. POST /api/runs/demo-1/rename-speaker with valid label
    rename_res = client.post(
        "/api/runs/demo-1/rename-speaker",
        json={"meeting_speaker_id": "ms-0001", "new_label": "Chị Hoa"},
    )
    assert rename_res.status_code == 200
    data = rename_res.json()
    assert data["status"] == "ok"
    assert data["old_label"] == "Người lạ 1"
    assert data["new_label"] == "Chị Hoa"

    # Verify timeline updated but status remains anonymous
    updated_timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    assert updated_timeline["segments"][0]["speaker_label"] == "Chị Hoa"
    assert updated_timeline["segments"][0]["speaker_status"] == "anonymous"

    # Verify audit file
    audit_file = run / "speaker_labels.json"
    assert audit_file.is_file()
    audit_data = json.loads(audit_file.read_text(encoding="utf-8"))
    assert audit_data["labels"]["ms-0001"] == "Chị Hoa"
    assert len(audit_data["history"]) == 1

    # Verify exports updated
    result_csv = (run / "exports" / "result.csv").read_text(encoding="utf-8")
    assert "Chị Hoa" in result_csv
    result_txt = (run / "exports" / "result.txt").read_text(encoding="utf-8")
    assert "Chị Hoa" in result_txt

    # 3. Error cases
    assert (
        client.post(
            "/api/runs/demo-1/rename-speaker",
            json={"meeting_speaker_id": "", "new_label": "Test"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/runs/demo-1/rename-speaker",
            json={"meeting_speaker_id": "ms-0001", "new_label": "   "},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/runs/demo-1/rename-speaker",
            json={"meeting_speaker_id": "ms-9999", "new_label": "Test"},
        ).status_code
        == 404
    )
