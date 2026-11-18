"""Local FastAPI demo for meeting transcription and source evidence."""

from __future__ import annotations

import json
import re
import shutil
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

import soundfile as sf
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.concurrency import run_in_threadpool

from meeting_pipeline.adapters.audio_io import probe_audio
from meeting_pipeline.application.speakers import SpeakerRegistry
from meeting_pipeline.config import PipelineConfig, load_config
from meeting_pipeline.domain.speaker_identity import person_identity_key
from meeting_pipeline.minutes.evidence_retrieval import load_indexed_turns
from meeting_pipeline.minutes.fact_extractor import M2RuleFactExtractor
from meeting_pipeline.minutes.model_runtime import ModelRuntimeError, model_status
from meeting_pipeline.minutes.renderer import render_completed_document
from meeting_pipeline.minutes.schema_mapper import load_schema
from meeting_pipeline.minutes.schemas import DocGraph
from meeting_pipeline.minutes.service import MinutesService
from meeting_pipeline.minutes.text_engine import MinutesOptions
from meeting_pipeline.pipeline.multi_source_fusion import MultiSourceFusionPipeline

Job = dict[str, Any]
WEB_DIR = Path(__file__).resolve().parent
TEMPLATES = Environment(
    loader=FileSystemLoader(WEB_DIR / "templates"),
    autoescape=select_autoescape(["html"]),
)
FUSION_METHODS = {
    "F1_BEST_SEGMENT": "Chọn toàn bộ transcript từ nguồn có điểm chất lượng transcript cao nhất.",
    "F3_ROVER": "Căn hàng từ rồi bỏ phiếu đều giữa các nguồn; hòa phiếu ưu tiên bỏ từ.",
    "F4_ASR_WEIGHTED": "Căn hàng từ rồi cộng điểm theo confidence ASR của từng token.",
    "F5_RULE_WEIGHTED": "Căn hàng từ rồi cộng điểm chất lượng transcript nhân confidence token.",
    "F5_RULE_WEIGHTED_CORRECTED": "F5 sửa: Luật bảo vệ nguồn chính, chống hallucination nguồn phụ.",
    "F6_LEARNED": "Căn hàng từ rồi dùng mô hình đã huấn luyện để chấm token; có thể chuyển về F5.",
}
IDENTITY_METHODS = {
    "prototype_cosine": "Đối chiếu mẫu giọng đã đăng ký, xét độ tương đồng và độ chênh lệch.",
    "mfcc_knn": "MFCC + KNN: so đặc trưng giọng với mẫu đăng ký, xét khoảng cách và margin.",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _row_person_key(row: dict[str, Any]) -> tuple[str, str] | None:
    return person_identity_key(
        str(row.get("speaker_label") or ""),
        row.get("speaker_id"),
        row.get("meeting_speaker_id"),
        str(row.get("speaker_status") or ""),
        int(row.get("speaker_count") or 1),
        row.get("overlap_group_id"),
    )


def _meeting_speakers(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in segments:
        key = _row_person_key(row)
        if key is not None and row.get("meeting_speaker_id"):
            groups.setdefault(key, []).append(row)
    return [
        {
            "meeting_speaker_id": group[0]["meeting_speaker_id"],
            "meeting_speaker_ids": list(dict.fromkeys(r["meeting_speaker_id"] for r in group)),
            "speaker_label": group[-1].get("speaker_label"),
            "speaker_status": group[-1].get("speaker_status") or "unknown",
            "speaker_id": group[-1].get("speaker_id"),
            "turn_count": len(group),
            "total_speech_sec": round(
                sum(
                    max(0.0, float(r.get("end_sec") or 0) - float(r.get("start_sec") or 0))
                    for r in group
                ),
                2,
            ),
        }
        for group in groups.values()
    ]


def _number(value: object, digits: int = 2, unit: str = "") -> str:
    if value is None or isinstance(value, bool):
        return "Chưa có dữ liệu"
    try:
        return f"{float(str(value)):.{digits}f}{unit}"
    except (TypeError, ValueError):
        return "Chưa có dữ liệu"


def _percent(value: object) -> str:
    if value is None or isinstance(value, bool):
        return "Chưa có dữ liệu"
    try:
        return f"{float(str(value)) * 100:.1f}%"
    except (TypeError, ValueError):
        return "Chưa có dữ liệu"


def _clock(value: object) -> str:
    try:
        seconds = max(0.0, float(str(value)))
    except (TypeError, ValueError):
        return "—"
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes):02d}:{rest:05.2f}"


TEMPLATES.filters.update(number=_number, percent=_percent, clock=_clock)


def _render(name: str, **context: object) -> HTMLResponse:
    return HTMLResponse(TEMPLATES.get_template(name).render(**context))


class DemoJobs:
    """Persist one local job per JSON file; inference runs outside request handling."""

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self.root = config.paths.data_dir / "demo_jobs"
        self.upload_root = config.paths.data_dir / "demo_uploads"
        self.speakers = SpeakerRegistry(config)
        self.pipeline_lock = threading.Lock()
        for path in self.root.glob("*.json"):
            job = _read_json(path)
            if job.get("status") in {"queued", "running"}:
                job.update(
                    status="failed",
                    completed_at=_now(),
                    error="Máy chủ đã khởi động lại khi đang xử lý. Hãy tạo lượt chạy mới.",
                )
                self.write(job)

    def path(self, job_id: str) -> Path:
        if re.fullmatch(r"[A-Za-z0-9_-]{1,100}", job_id) is None:
            raise KeyError(job_id)
        return self.root / f"{job_id}.json"

    def read(self, job_id: str) -> Job:
        path = self.path(job_id)
        if not path.is_file():
            for run_path in self.config.paths.data_dir.glob(f"meetings/*/runs/{job_id}"):
                if run_path.is_dir():
                    manifest = _read_json(run_path / "manifest.json")
                    return {
                        "job_id": job_id,
                        "meeting_name": manifest.get("meeting_name", f"Cuộc họp {job_id[:8]}"),
                        "status": "succeeded",
                        "run_dir": str(run_path.resolve()),
                        "source_paths": [],
                        "source_names": [
                            str(s.get("original_name", s.get("source_id", "")))
                            for s in manifest.get("sources", [])
                        ],
                        "created_at": manifest.get("created_at", _now()),
                    }
            raise KeyError(job_id)
        return _read_json(path)

    def write(self, job: Job) -> None:
        _write_json(self.path(str(job["job_id"])), job)

    def list(self) -> list[Job]:
        jobs = [_read_json(path) for path in self.root.glob("*.json")]
        existing_ids = {str(j.get("job_id")) for j in jobs}
        for run_path in self.config.paths.data_dir.glob("meetings/*/runs/*"):
            if run_path.is_dir() and run_path.name not in existing_ids:
                manifest = _read_json(run_path / "manifest.json")
                if manifest:
                    jobs.append(
                        {
                            "job_id": run_path.name,
                            "meeting_name": manifest.get(
                                "meeting_name", f"Cuộc họp {run_path.name[:8]}"
                            ),
                            "status": "succeeded",
                            "run_dir": str(run_path.resolve()),
                            "source_paths": [],
                            "source_names": [
                                str(s.get("original_name", s.get("source_id", "")))
                                for s in manifest.get("sources", [])
                            ],
                            "created_at": manifest.get("created_at", _now()),
                        }
                    )
        return sorted(jobs, key=lambda item: str(item.get("created_at", "")), reverse=True)

    def execute(self, job_id: str) -> None:
        with self.pipeline_lock:
            job = self.read(job_id)
            job.update(status="running", started_at=_now(), error=None)
            self.write(job)
            try:
                profiles = self.speakers.load(
                    [str(value) for value in job.get("participant_ids", [])]
                )
                run_config = self.config.model_copy(deep=True)
                run_config.identity["method"] = str(job["identity_method"])
                run_dir = MultiSourceFusionPipeline(run_config).run(
                    str(job["meeting_name"]),
                    [Path(value) for value in job["source_paths"]],
                    profiles,
                    fusion_method=str(job["fusion_method"]),
                )
            except Exception as exc:
                job.update(status="failed", completed_at=_now(), error=str(exc))
                self.write(job)
                return
            job.update(status="succeeded", completed_at=_now(), run_dir=str(run_dir.resolve()))
            self.write(job)


def _job_or_404(store: DemoJobs, job_id: str) -> Job:
    try:
        return store.read(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy lượt chạy") from exc


def _run_dir(job: Job) -> Path:
    if job.get("status") != "succeeded" or not job.get("run_dir"):
        raise HTTPException(status_code=409, detail="Lượt chạy chưa hoàn tất")
    return Path(str(job["run_dir"]))


def _artifact_path(run_dir: Path, relative_path: str) -> Path:
    root = run_dir.resolve()
    candidate = (root / relative_path).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Không tìm thấy tệp kết quả")
    return candidate


async def _save_uploads(uploads: list[UploadFile], destination: Path, max_bytes: int) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=False)
    saved: list[Path] = []
    try:
        for index, upload in enumerate(uploads, start=1):
            filename = Path(upload.filename or f"source-{index}").name
            target = destination / f"{index:02d}-{filename}"
            size = 0
            with target.open("wb") as handle:
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise HTTPException(status_code=413, detail=f"Tệp quá lớn: {filename}")
                    handle.write(chunk)
            await upload.close()
            if size == 0:
                raise HTTPException(status_code=400, detail=f"Tệp rỗng: {filename}")
            try:
                probe_audio(target)
            except Exception as exc:
                raise HTTPException(
                    status_code=400, detail=f"Không đọc được âm thanh: {filename}"
                ) from exc
            saved.append(target.resolve())
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return saved


async def _save_template_upload(
    upload: UploadFile, destination_file: Path, max_bytes: int = 50 * 1024 * 1024
) -> Path:
    destination_file.parent.mkdir(parents=True, exist_ok=True)
    filename = upload.filename or "template.docx"
    ext = Path(filename).suffix.lower()
    if ext not in {".doc", ".docx"}:
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ tệp Word (.doc, .docx)")
    size = 0
    with destination_file.open("wb") as buffer:
        while chunk := await upload.read(1024 * 1024):
            size += len(chunk)
            if size > max_bytes:
                raise HTTPException(
                    status_code=413, detail="Tệp mẫu Word vượt quá dung lượng cho phép"
                )
            buffer.write(chunk)
    await upload.close()
    if size == 0:
        raise HTTPException(status_code=400, detail="Tệp mẫu Word rỗng")
    return destination_file


def _result_context(
    job_id: str, job: Job, run_dir: Path, speakers: SpeakerRegistry
) -> dict[str, object]:
    timeline_data = _read_json(run_dir / "timeline.json")
    coverage = _read_json(run_dir / "coverage.json")
    manifest = _read_json(run_dir / "manifest.json")
    segments = timeline_data.get("segments") or []
    sources = coverage.get("sources") or []
    names = {str(row.get("source_id", "")): str(row.get("original_name", "")) for row in sources}
    method_used = manifest.get("fusion_method_used")
    method_requested = manifest.get("fusion_method_requested") or job.get("fusion_method")
    identity_method = manifest.get("identity_method_used") or job.get("identity_method")
    source_count = len(sources) or len(job.get("source_names") or [])
    aligned_files = sorted((run_dir / "aligned").glob("*.wav"))
    duration = max(
        [float(row.get("duration_sec") or row.get("end_sec") or 0) for row in sources]
        + [float(row.get("end_sec") or 0) for row in segments],
        default=0.0,
    )
    if aligned_files:
        duration = max(duration, *(sf.info(path).duration for path in aligned_files))

    def artifact_url(relative_path: object) -> str | None:
        if not isinstance(relative_path, str) or not relative_path:
            return None
        try:
            _artifact_path(run_dir, relative_path)
        except HTTPException:
            return None
        return f"/api/runs/{job_id}/files/{quote(relative_path, safe='/')}"

    return {
        "job": job,
        "job_id": job_id,
        "segments": segments,
        "sources": sources,
        "source_names": names,
        "manifest": manifest,
        "coverage": coverage,
        "schema_version": timeline_data.get("schema_version", "1.0"),
        "fusion_requested": method_requested,
        "fusion_used": method_used,
        "fusion_description": FUSION_METHODS.get(str(method_used), "Chưa có dữ liệu"),
        "fusion_fallback": bool(
            method_requested and method_used and method_requested != method_used
        ),
        "identity_method": identity_method,
        "identity_description": IDENTITY_METHODS.get(str(identity_method), "Chưa có dữ liệu"),
        "source_count": source_count,
        "duration": duration,
        "identified_count": len(
            {
                str(row.get("speaker_id"))
                for row in segments
                if row.get("speaker_status") == "identified" and row.get("speaker_id")
            }
        ),
        "stranger_cluster_count": len(
            {
                str(row.get("meeting_speaker_id") or row.get("speaker_label"))
                for row in segments
                if row.get("speaker_status") == "anonymous"
            }
        ),
        "ambiguous_count": sum(
            1
            for row in segments
            if row.get("speaker_status") == "ambiguous"
            and not row.get("overlap_group_id")
            and int(row.get("speaker_count") or 1) == 1
        ),
        "overlap_not_run_count": sum(
            1
            for row in segments
            if (row.get("asr_status") == "not_run" or row.get("overlap_group_id") is not None)
        ),
        "unknown_count": len(
            {
                _row_person_key(row)
                for row in segments
                if row.get("speaker_status") != "identified" and _row_person_key(row) is not None
            }
        ),
        "meeting_speakers": _meeting_speakers(segments),
        "reference_source_id": coverage.get("reference_source_id"),
        "aligned_files": aligned_files,
        "extra_aligned_files": [
            path
            for path in aligned_files
            if path.stem not in {str(row.get("source_id", "")) for row in sources}
        ],
        "speaker_names": {
            str(profile.get("speaker_id")): str(profile.get("display_name"))
            for profile in speakers.list_profiles()
        },
        "artifact_url": artifact_url,
        "has_minutes": bool((run_dir / "exports" / "completed.docx").is_file()),
        "minutes_manifest": _read_json(run_dir / "minutes" / "manifest.json")
        if (run_dir / "minutes" / "manifest.json").is_file()
        else None,
        "minutes_schema": _read_json(run_dir / "template" / "schema.json")
        if (run_dir / "template" / "schema.json").is_file()
        else None,
        "minutes_facts": json.loads(
            (run_dir / "minutes" / "facts.json").read_text(encoding="utf-8")
        )
        if (run_dir / "minutes" / "facts.json").is_file()
        else [],
        "has_preview_before": (run_dir / "template" / "preview_before.png").is_file(),
        "has_preview_after": (run_dir / "exports" / "preview_after.png").is_file(),
        "preview_before_url": artifact_url("template/preview_before.png"),
        "preview_after_url": artifact_url("exports/preview_after.png"),
        "has_completed_docx": (run_dir / "exports" / "completed.docx").is_file(),
        "has_completed_zip": (run_dir / "exports" / "completed_minutes.zip").is_file(),
        "minutes_model_report": _read_json(run_dir / "minutes/model_report.json"),
        "minutes_configuration": _read_json(run_dir / "minutes/configuration.json"),
        "minutes_formatting_report": _read_json(run_dir / "minutes/formatting_report.json"),
        "doc_graph_summary": {
            "template_id": _read_json(run_dir / "template" / "doc_graph.json").get(
                "template_id", ""
            ),
            "candidate_count": len(
                _read_json(run_dir / "template" / "doc_graph.json").get("candidates", [])
            ),
            "block_count": len(
                _read_json(run_dir / "template" / "doc_graph.json").get("blocks", [])
            ),
        }
        if (run_dir / "template" / "doc_graph.json").is_file()
        else None,
    }


def create_app(config: PipelineConfig | None = None) -> FastAPI:
    """Create the demo application; model weights load only for jobs."""
    config = config or load_config(Path("configs/default.yaml"))
    store = DemoJobs(config)
    app = FastAPI(title="Demo nhận diện người nói và dung hợp transcript")
    app.state.demo_jobs = store
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return _render(
            "index.html",
            title="Tạo cuộc họp",
            speakers=store.speakers.list_profiles(),
            jobs=store.list(),
            max_sources=config.audio.max_sources,
            fusion_methods=FUSION_METHODS,
            identity_methods=IDENTITY_METHODS,
        )

    @app.post("/api/speakers")
    async def enroll_speaker(
        display_name: Annotated[str, Form(min_length=1, max_length=200)],
        samples: Annotated[list[UploadFile], File()],
    ) -> dict[str, object]:
        if not display_name.strip():
            raise HTTPException(status_code=400, detail="Hãy nhập tên người tham gia")
        if not 1 <= len(samples) <= 8:
            raise HTTPException(status_code=400, detail="Cần 1 đến 8 mẫu giọng")
        destination = config.paths.data_dir / "speaker_uploads" / str(uuid.uuid4())
        paths = await _save_uploads(samples, destination, config.audio.max_upload_bytes)
        try:
            return store.speakers.enroll(display_name, paths)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/runs", status_code=status.HTTP_202_ACCEPTED)
    async def create_run(
        background: BackgroundTasks,
        meeting_name: Annotated[str, Form(min_length=1, max_length=200)],
        sources: Annotated[list[UploadFile], File()],
        participant_ids: Annotated[list[str] | None, Form()] = None,
        identity_method: Annotated[str, Form()] = "prototype_cosine",
        fusion_method: Annotated[str, Form()] = "F5_RULE_WEIGHTED",
    ) -> JSONResponse:
        if not meeting_name.strip():
            raise HTTPException(status_code=400, detail="Hãy nhập tên cuộc họp")
        if not 1 <= len(sources) <= config.audio.max_sources:
            raise HTTPException(status_code=400, detail="Cần 1 đến 8 tệp âm thanh")
        if identity_method not in IDENTITY_METHODS or fusion_method not in FUSION_METHODS:
            raise HTTPException(status_code=400, detail="Phương pháp được chọn không hợp lệ")
        selected_profiles = participant_ids or []
        known_profiles = {
            str(profile.get("speaker_id")) for profile in store.speakers.list_profiles()
        }
        if any(profile_id not in known_profiles for profile_id in selected_profiles):
            raise HTTPException(status_code=400, detail="Có hồ sơ người tham gia không tồn tại")
        job_id = str(uuid.uuid4())
        paths = await _save_uploads(
            sources, store.upload_root / job_id, config.audio.max_upload_bytes
        )
        job: Job = {
            "job_id": job_id,
            "meeting_name": meeting_name.strip(),
            "status": "queued",
            "source_paths": [str(path) for path in paths],
            "source_names": [path.name for path in paths],
            "participant_ids": selected_profiles,
            "identity_method": identity_method,
            "fusion_method": fusion_method,
            "created_at": _now(),
            "started_at": None,
            "completed_at": None,
            "run_dir": None,
            "error": None,
        }
        store.write(job)
        background.add_task(store.execute, job_id)
        return JSONResponse({"job_id": job_id, "status": "queued"}, status_code=202)

    @app.get("/api/runs/{job_id}")
    def run_status(job_id: str) -> Job:
        job = _job_or_404(store, job_id)
        return {key: value for key, value in job.items() if key != "source_paths"}

    @app.get("/runs/{job_id}", response_class=HTMLResponse)
    def run_page(job_id: str) -> HTMLResponse:
        job = _job_or_404(store, job_id)
        if job.get("status") != "succeeded":
            return _render("state.html", title=str(job.get("meeting_name", "")), job=job)
        run_dir = _run_dir(job)
        return _render(
            "result.html",
            title=str(job.get("meeting_name", "")),
            **_result_context(job_id, job, run_dir, store.speakers),
        )

    @app.get("/api/runs/{job_id}/speakers")
    def get_run_speakers(job_id: str) -> list[dict[str, Any]]:
        job = _job_or_404(store, job_id)
        run_dir = _run_dir(job)
        timeline_data = _read_json(run_dir / "timeline.json")
        segments = timeline_data.get("segments") or []
        return _meeting_speakers(segments)

    @app.post("/api/runs/{job_id}/rename-speaker")
    def rename_speaker(
        job_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        job = _job_or_404(store, job_id)
        run_dir = _run_dir(job)
        meeting_speaker_id = str(payload.get("meeting_speaker_id", "")).strip()
        new_label = str(payload.get("new_label", "")).strip()
        if not meeting_speaker_id:
            raise HTTPException(status_code=400, detail="Thiếu meeting_speaker_id")
        if not new_label:
            raise HTTPException(status_code=400, detail="Nhãn mới không được để trống")
        if len(new_label) > 100:
            raise HTTPException(status_code=400, detail="Nhãn quá dài (tối đa 100 ký tự)")
        clean_label = re.sub(r"[\r\n\t]+", " ", new_label).strip()

        timeline_path = run_dir / "timeline.json"
        timeline_data = _read_json(timeline_path)
        segments = timeline_data.get("segments") or []
        if not segments:
            raise HTTPException(status_code=404, detail="Không tìm thấy timeline")

        target = next(
            (r for r in segments if r.get("meeting_speaker_id") == meeting_speaker_id), None
        )
        target_key = _row_person_key(target) if target else None
        related_ids = {
            r.get("meeting_speaker_id")
            for r in segments
            if r.get("meeting_speaker_id")
            and target_key is not None
            and _row_person_key(r) == target_key
        }

        matched = False
        old_label = ""
        for seg in segments:
            if seg.get("meeting_speaker_id") in related_ids:
                if not old_label:
                    old_label = str(seg.get("speaker_label", ""))
                seg["speaker_label"] = clean_label
                matched = True

        if not matched:
            raise HTTPException(
                status_code=404, detail=f"Không tìm thấy speaker {meeting_speaker_id}"
            )

        timeline_data["segments"] = segments
        _write_json(timeline_path, timeline_data)

        labels_path = run_dir / "speaker_labels.json"
        audit_data = _read_json(labels_path)
        history = audit_data.get("history") or []
        labels_map = audit_data.get("labels") or {}
        for related_id in related_ids:
            if related_id:
                labels_map[related_id] = clean_label
        history.append(
            {
                "meeting_speaker_id": meeting_speaker_id,
                "meeting_speaker_ids": sorted(str(i) for i in related_ids if i),
                "old_label": old_label,
                "new_label": clean_label,
                "updated_at": _now(),
            }
        )
        _write_json(
            labels_path,
            {
                "schema_version": "2.0",
                "updated_at": _now(),
                "labels": labels_map,
                "history": history,
            },
        )

        MultiSourceFusionPipeline._write_exports(run_dir, segments)

        return {
            "status": "ok",
            "job_id": job_id,
            "meeting_speaker_id": meeting_speaker_id,
            "old_label": old_label,
            "new_label": clean_label,
        }

    @app.get("/api/runs/{job_id}/timeline")
    def timeline(job_id: str) -> FileResponse:
        path = _artifact_path(_run_dir(_job_or_404(store, job_id)), "timeline.json")
        return FileResponse(path)

    @app.get("/api/runs/{job_id}/export")
    def export(job_id: str, format: str = "zip") -> FileResponse:
        if format not in {"json", "csv", "txt", "zip"}:
            raise HTTPException(status_code=400, detail="Định dạng tải xuống không hợp lệ")
        path = _artifact_path(_run_dir(_job_or_404(store, job_id)), f"exports/result.{format}")
        return FileResponse(path, filename=path.name)

    @app.get("/api/runs/{job_id}/files/{relative_path:path}")
    def artifact(job_id: str, relative_path: str) -> FileResponse:
        path = _artifact_path(_run_dir(_job_or_404(store, job_id)), relative_path)
        return FileResponse(path)

    @app.post("/api/runs/{job_id}/template")
    async def upload_run_template(
        job_id: str,
        template: Annotated[UploadFile, File()],
        use_model: Annotated[bool, Form()] = False,
        minutes_mode: Annotated[str, Form()] = "detailed",
        use_fcm: Annotated[bool, Form()] = True,
        correct_transcript: Annotated[bool, Form()] = True,
        content_field_id: Annotated[str | None, Form()] = None,
        format_standard: Annotated[str, Form()] = "nd30_2020",
        two_sided: Annotated[bool, Form()] = False,
        document_metadata: Annotated[str, Form()] = "{}",
    ) -> JSONResponse:
        job = _job_or_404(store, job_id)
        run_dir = _run_dir(job)
        temp_dest = run_dir / "template" / "upload_temp" / (template.filename or "template.docx")
        saved_path = await _save_template_upload(template, temp_dest)
        meeting_meta = {
            "meeting_name": job.get("meeting_name", ""),
            "job_id": job_id,
        }
        minutes_svc = MinutesService()
        try:
            options = MinutesOptions.model_validate(
                {
                    "mode": minutes_mode,
                    "use_model": use_model,
                    "use_fcm": use_fcm,
                    "correct_transcript": correct_transcript,
                    "content_field_id": content_field_id or None,
                    "format_standard": format_standard,
                    "two_sided": two_sided,
                    "document_metadata": json.loads(document_metadata),
                }
            )
            result = await run_in_threadpool(
                minutes_svc.process_template_for_run,
                template_file_path=saved_path,
                run_dir=run_dir,
                meeting_metadata=meeting_meta,
                use_model=use_model,
                options=options,
            )
            return JSONResponse(result)
        except ModelRuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Lỗi xử lý biểu mẫu Word: {exc}") from exc
        finally:
            if saved_path.is_file():
                shutil.rmtree(temp_dest.parent, ignore_errors=True)

    @app.get("/api/minutes/models")
    def get_minutes_models() -> dict[str, Any]:
        return model_status()

    @app.post("/api/runs/{job_id}/minutes/regenerate")
    async def regenerate_minutes(job_id: str, options: MinutesOptions) -> dict[str, Any]:
        run_dir = _run_dir(_job_or_404(store, job_id))
        try:
            return await run_in_threadpool(MinutesService().regenerate, run_dir, options)
        except ModelRuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/runs/{job_id}/minutes")
    def get_run_minutes(job_id: str) -> dict[str, Any]:
        job = _job_or_404(store, job_id)
        run_dir = _run_dir(job)
        manifest_path = run_dir / "minutes" / "manifest.json"
        schema_path = run_dir / "template" / "schema.json"
        facts_path = run_dir / "minutes" / "facts.json"
        doc_graph_path = run_dir / "template" / "doc_graph.json"

        has_template = (run_dir / "exports" / "completed.docx").is_file()
        return {
            "has_template": has_template,
            "manifest": _read_json(manifest_path) if manifest_path.is_file() else None,
            "schema": _read_json(schema_path) if schema_path.is_file() else None,
            "facts": json.loads(facts_path.read_text(encoding="utf-8"))
            if facts_path.is_file()
            else [],
            "doc_graph_summary": {
                "template_id": _read_json(doc_graph_path).get("template_id", ""),
                "candidate_count": len(_read_json(doc_graph_path).get("candidates", [])),
            }
            if doc_graph_path.is_file()
            else None,
            "has_preview_before": (run_dir / "template" / "preview_before.png").is_file(),
            "has_preview_after": (run_dir / "exports" / "preview_after.png").is_file(),
            "model_report": _read_json(run_dir / "minutes/model_report.json"),
            "configuration": _read_json(run_dir / "minutes/configuration.json"),
            "formatting_report": _read_json(run_dir / "minutes/formatting_report.json"),
            "topics": _read_json(run_dir / "minutes/topics.json"),
        }

    @app.post("/api/runs/{job_id}/minutes/format")
    async def format_existing_minutes(job_id: str, options: MinutesOptions) -> dict[str, str]:
        run_dir = _run_dir(_job_or_404(store, job_id))
        try:
            await run_in_threadpool(MinutesService().reformat_existing, run_dir, options)
            return {"status": "ok", "message": "Đã áp dụng thể thức cho nội dung đã điền."}
        except ModelRuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/runs/{job_id}/template/schema")
    def update_run_schema(
        job_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        job = _job_or_404(store, job_id)
        run_dir = _run_dir(job)
        fields = payload.get("fields")
        if not isinstance(fields, list):
            raise HTTPException(status_code=400, detail="Trường 'fields' phải là danh sách")
        minutes_svc = MinutesService()
        try:
            minutes_svc.update_schema_and_re_extract(run_dir, fields)
            return {"status": "ok", "message": "Đã cập nhật schema và trích xuất lại fact"}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/runs/{job_id}/minutes/facts")
    def update_run_facts(
        job_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        job = _job_or_404(store, job_id)
        run_dir = _run_dir(job)
        facts = payload.get("facts")
        if not isinstance(facts, list):
            raise HTTPException(status_code=400, detail="Trường 'facts' phải là danh sách")
        minutes_svc = MinutesService()
        try:
            minutes_svc.update_facts_and_re_render(run_dir, facts)
            return {
                "status": "ok",
                "message": "Đã cập nhật fact và điền lại Word mà không gọi ASR",
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/runs/{job_id}/edit-transcript")
    def edit_transcript(
        job_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        job = _job_or_404(store, job_id)
        run_dir = _run_dir(job)
        segment_index = payload.get("segment_index")
        new_text = str(payload.get("new_text", "")).strip()
        if segment_index is None:
            raise HTTPException(status_code=400, detail="Thiếu segment_index")
        try:
            seg_idx = int(segment_index)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="segment_index phải là số nguyên") from exc

        timeline_path = run_dir / "timeline.json"
        timeline_data = _read_json(timeline_path)
        segments = timeline_data.get("segments") or []
        if not (0 <= seg_idx < len(segments)):
            raise HTTPException(status_code=404, detail="Không tìm thấy đoạn hội thoại")

        old_text = segments[seg_idx].get("text", "")
        segments[seg_idx]["text"] = new_text
        segments[seg_idx]["user_edited"] = True
        timeline_data["segments"] = segments
        _write_json(timeline_path, timeline_data)

        # Update exports (json, csv, txt)
        MultiSourceFusionPipeline._write_exports(run_dir, segments)

        # If template minutes exist, re-extract facts and re-render without calling ASR
        schema_path = run_dir / "template" / "schema.json"
        doc_graph_path = run_dir / "template" / "doc_graph.json"
        normalized_docx = run_dir / "template" / "normalized.docx"
        completed_docx = run_dir / "exports" / "completed.docx"
        configuration = _read_json(run_dir / "minutes/configuration.json")
        if configuration.get("use_model"):
            report = _read_json(run_dir / "minutes/model_report.json")
            report["stale_since_transcript_edit"] = True
            _write_json(run_dir / "minutes/model_report.json", report)
        elif schema_path.is_file() and doc_graph_path.is_file() and normalized_docx.is_file():
            schema = load_schema(schema_path)
            turns = load_indexed_turns(run_dir)
            extractor = M2RuleFactExtractor()
            facts = extractor.extract_facts(
                schema=schema,
                turns=turns,
                meeting_metadata={"meeting_name": job.get("meeting_name", ""), "job_id": job_id},
                run_id=run_dir.name,
            )
            minutes_dir = run_dir / "minutes"
            _write_json(minutes_dir / "facts.json", [f.model_dump() for f in facts])

            doc_graph = DocGraph.model_validate(
                json.loads(doc_graph_path.read_text(encoding="utf-8"))
            )
            render_completed_document(
                normalized_docx_path=normalized_docx,
                output_docx_path=completed_docx,
                doc_graph=doc_graph,
                schema=schema,
                facts=facts,
            )

        return {
            "status": "ok",
            "job_id": job_id,
            "segment_index": seg_idx,
            "old_text": old_text,
            "new_text": new_text,
        }

    @app.get("/api/runs/{job_id}/minutes/download")
    def download_minutes(job_id: str, format: str = "docx") -> FileResponse:
        job = _job_or_404(store, job_id)
        run_dir = _run_dir(job)
        if format == "docx":
            path = _artifact_path(run_dir, "exports/completed.docx")
            return FileResponse(
                path,
                filename=f"bien_ban_{job_id[:8]}.docx",
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        elif format == "zip":
            path = _artifact_path(run_dir, "exports/completed_minutes.zip")
            return FileResponse(
                path,
                filename=f"bien_ban_kem_manifest_{job_id[:8]}.zip",
                media_type="application/zip",
            )
        elif format == "manifest":
            path = _artifact_path(run_dir, "minutes/manifest.json")
            return FileResponse(
                path,
                filename="manifest.json",
                media_type="application/json",
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="Định dạng tải về không hỗ trợ (chọn docx, zip, hoặc manifest)",
            )

    @app.get("/api/runs/{job_id}/minutes/preview/{preview_type}")
    def get_minutes_preview(job_id: str, preview_type: str) -> FileResponse:
        job = _job_or_404(store, job_id)
        run_dir = _run_dir(job)
        if preview_type == "before":
            path = _artifact_path(run_dir, "template/preview_before.png")
        elif preview_type == "after":
            path = _artifact_path(run_dir, "exports/preview_after.png")
        else:
            raise HTTPException(
                status_code=400, detail="preview_type phải là 'before' hoặc 'after'"
            )
        return FileResponse(path, media_type="image/png")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
