"""Wave 3B: Document PDF/Scan ingest (ingest.reconstruct), Visual Preview, M0 vs Qwen3 Schema Mapping, and Backend API/Artifact latency."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import OUT, ROOT, log, read_json, rss_mb, setup_root_src, write_csv, write_json


def _make_pdf_variants(src_path: Path, work: Path) -> dict[str, Path]:
    """Convert DOCX/DOC to vector PDF via LibreOffice, then create flat-scanned & 1.2deg-skewed image PDFs."""
    from PIL import Image, ImageFilter

    vec_dir = work / "vec"
    vec_dir.mkdir(parents=True, exist_ok=True)
    res = subprocess.run(
        ["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(vec_dir), str(src_path)],
        capture_output=True,
        text=True,
        timeout=90,
        check=True,
    )
    _ = res
    vec_pdf = vec_dir / f"{src_path.stem}.pdf"
    if not vec_pdf.is_file():
        raise RuntimeError(f"Missing converted PDF: {vec_pdf}")

    # Rasterize pages at 200 DPI
    png_prefix = work / f"{src_path.stem}_page"
    subprocess.run(
        ["pdftoppm", "-r", "200", "-png", str(vec_pdf), str(png_prefix)],
        capture_output=True,
        text=True,
        timeout=90,
        check=True,
    )
    png_pages = sorted(work.glob(f"{src_path.stem}_page-*.png"))

    def pack_pdf(dst: Path, skew_deg: float, quality: int) -> Path:
        imgs = []
        for p in png_pages:
            im = Image.open(p).convert("RGB")
            im = im.filter(ImageFilter.GaussianBlur(0.35 if skew_deg == 0 else 0.55))
            if skew_deg:
                im = im.rotate(skew_deg, resample=Image.Resampling.BICUBIC, expand=False, fillcolor="white")
            # Simulate JPEG scan compression before packing to PDF
            import io

            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=quality)
            imgs.append(Image.open(io.BytesIO(buf.getvalue())).convert("RGB"))
        imgs[0].save(dst, "PDF", resolution=200.0, save_all=True, append_images=imgs[1:])
        return dst

    flat_pdf = pack_pdf(work / f"{src_path.stem}_scan_flat.pdf", skew_deg=0.0, quality=75)
    skew_pdf = pack_pdf(work / f"{src_path.stem}_scan_skew1.2.pdf", skew_deg=1.2, quality=55)
    return {
        "vector_pdf": vec_pdf,
        "scanned_flat_pdf": flat_pdf,
        "scanned_skew_1.2deg_pdf": skew_pdf,
    }


def benchmark_doc_ingest_and_schema() -> dict:
    from docx import Document

    from meeting_backend.processing.documents.ingest import reconstruct
    from meeting_pipeline.minutes.converter import normalize_template
    from meeting_pipeline.minutes.doc_parser import parse_template_document
    from meeting_pipeline.minutes.model_runtime import ModelSession, load_model_settings
    from meeting_pipeline.minutes.schema_mapper import M0RuleSchemaMapper, M1Qwen3SchemaMapper
    from meeting_pipeline.minutes.schemas import SemanticFieldType
    from meeting_pipeline.minutes.visual_qa import render_document_pages

    fixtures_tpl = ROOT / "tests/fixtures/templates"
    fixtures_gt = ROOT / "tests/fixtures/ground_truth"
    specs = [
        ("bien_ban_hop_chi_bo.docx", "bien_ban_hop_chi_bo_gold.json"),
        ("mau_bien_ban_hop_chung.doc", "mau_bien_ban_hop_chung_gold.json"),
        ("bien_ban_ban_giao_thiet_bi.docx", None),
    ]
    mapper = M0RuleSchemaMapper()
    m1_probe = M1Qwen3SchemaMapper()

    rows = []
    preview_rows = []
    m1_rows = []
    qwen_prompt_tasks = []

    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        ocr_cache = ROOT / "data/ocr_cache"

        for tpl_name, gt_name in specs:
            tpl_path = fixtures_tpl / tpl_name
            gt_types = None
            if gt_name:
                gt = read_json(fixtures_gt / gt_name)
                gt_types = {f["semantic_type"] for f in gt.get("fields", [])}

            # Baseline DOCX/DOC
            t0 = time.perf_counter()
            conv = normalize_template(tpl_path, work / f"orig_{tpl_path.stem}")
            doc_graph_base = parse_template_document(conv.normalized_docx_path, original_sha256=conv.original_sha256)
            schema_base = mapper.propose_schema(doc_graph_base)
            t_base = time.perf_counter() - t0
            base_tables = len(Document(conv.normalized_docx_path).tables)

            # Check built-in M1 availability status
            _, m1_status, m1_dur = m1_probe.propose_schema(doc_graph_base)
            m1_rows.append(
                {
                    "template": tpl_name,
                    "builtin_m1_status": m1_status,
                    "builtin_m1_check_sec": round(m1_dur, 4),
                    "m0_fields": len(schema_base.fields),
                    "m0_recall": round(len(gt_types & {f.semantic_type.value for f in schema_base.fields}) / max(len(gt_types), 1), 4) if gt_types else None,
                    "m0_needs_review": sum(f.mapper_status == "needs_review" for f in schema_base.fields),
                }
            )
            if gt_types:
                qwen_prompt_tasks.append((tpl_name, doc_graph_base, gt_types, schema_base))

            # Preview rendering time via LibreOffice + Poppler
            tp0 = time.perf_counter()
            pages = render_document_pages(conv.normalized_docx_path, work / f"preview_{tpl_path.stem}")
            tp_dt = time.perf_counter() - tp0
            preview_rows.append(
                {
                    "template": tpl_name,
                    "pages_rendered": len(pages),
                    "render_pages_sec": round(tp_dt, 3),
                }
            )

            rows.append(
                {
                    "template": tpl_name,
                    "input_variant": "native_doc_docx",
                    "engine": conv.conversion_engine,
                    "pages": len(pages),
                    "anchors": len(doc_graph_base.all_anchors),
                    "baseline_anchors": len(doc_graph_base.all_anchors),
                    "tables_recovered": base_tables,
                    "baseline_tables": base_tables,
                    "schema_fields": len(schema_base.fields),
                    "semantic_type_recall": m1_rows[-1]["m0_recall"],
                    "ingest_sec": round(t_base, 3),
                }
            )

            # Build PDF variants & test ingest.reconstruct()
            pdfs = _make_pdf_variants(conv.normalized_docx_path, work / f"pdfs_{tpl_path.stem}")
            for variant, pdf_path in pdfs.items():
                dst_docx = work / f"reconstructed_{tpl_path.stem}_{variant}.docx"
                dst_docx.parent.mkdir(parents=True, exist_ok=True)
                ti0 = time.perf_counter()
                rep = reconstruct(pdf_path, dst_docx, ocr_cache, stage=lambda _s: None)
                ti_dt = time.perf_counter() - ti0
                dg = parse_template_document(dst_docx, original_sha256="bench")
                sch = mapper.propose_schema(dg)
                tbl_cnt = len(Document(dst_docx).tables)
                rec_val = (
                    round(len(gt_types & {f.semantic_type.value for f in sch.fields}) / max(len(gt_types), 1), 4)
                    if gt_types
                    else None
                )
                rows.append(
                    {
                        "template": tpl_name,
                        "input_variant": variant,
                        "engine": rep["engine"],
                        "pages": len(rep["pages"]),
                        "anchors": len(dg.all_anchors),
                        "baseline_anchors": len(doc_graph_base.all_anchors),
                        "tables_recovered": tbl_cnt,
                        "baseline_tables": base_tables,
                        "schema_fields": len(sch.fields),
                        "semantic_type_recall": rec_val,
                        "ingest_sec": round(ti_dt, 3),
                    }
                )
                log(f"[Wave3B Ingest] {tpl_name} [{variant}]: engine={rep['engine']} anchors={len(dg.all_anchors)}/{len(doc_graph_base.all_anchors)} tables={tbl_cnt}/{base_tables} recall={rec_val} ({ti_dt:.2f}s)")

        # Compare M1 prompt executed via local Qwen3-4B MLX vs M0RuleSchemaMapper
        if qwen_prompt_tasks:
            settings = load_model_settings().model_copy(update={"response_cache": False, "adapter_path": None})
            valid_types = [t.value for t in SemanticFieldType]
            sys_prompt = (
                "Bạn là bộ ánh xạ trường biểu mẫu biên bản tiếng Việt. "
                f"Chỉ dùng các semantic_type trong danh sách: {valid_types}. "
                'Trả JSON {"mappings":[{"anchor_id":"...","semantic_type":"..."}]} đủ các anchor cần điền.'
            )
            with ModelSession(work / "m1_mlx.log", settings) as session:
                for idx_q, (tpl_name, dg_base, gt_types, sch_m0) in enumerate(qwen_prompt_tasks):
                    ts0 = time.perf_counter()
                    prompt = {"anchors": json.loads(m1_probe._build_prompt(dg_base))}
                    try:
                        parsed = session.generate_json(sys_prompt, prompt)
                        raw_maps = parsed.get("mappings") if isinstance(parsed, dict) else []
                        pred_types = {
                            item.get("semantic_type")
                            for item in (raw_maps or [])
                            if isinstance(item, dict) and item.get("semantic_type") in valid_types
                        }
                        m1_recall = round(len(gt_types & pred_types) / max(len(gt_types), 1), 4)
                        m1_count = len(raw_maps or [])
                    except Exception as exc:
                        m1_recall = None
                        m1_count = 0
                        log(f"[Wave3B M1 MLX] {tpl_name} error: {exc}")
                    m1_dt = time.perf_counter() - ts0
                    for row in m1_rows:
                        if row["template"] == tpl_name:
                            row["qwen3_mlx_schema_sec"] = round(m1_dt, 3)
                            row["qwen3_mlx_mapped_count"] = m1_count
                            row["qwen3_mlx_recall"] = m1_recall

    return {"ingest": rows, "previews": preview_rows, "schema_mappers": m1_rows}


def benchmark_backend_components() -> dict:
    """Measure ArtifactStore SHA-256 register/verify throughput & FastAPI HTTP/Pydantic route overhead (no live mongod on host)."""
    import numpy as np
    import soundfile as sf
    from fastapi.testclient import TestClient

    from meeting_backend.core.settings import Settings
    from meeting_backend.infrastructure.artifacts.store import ArtifactStore
    from meeting_backend.main import create_app

    # 1. Measure ArtifactStore register + resolve throughput across realistic payload sizes (5MB, 25MB WAV)
    class _MemColl:
        def __init__(self):
            self.rows = []

        def find_one(self, flt):
            for r in self.rows:
                if all(r.get(k) == v for k, v in flt.items()):
                    return r
            return None

        def insert_one(self, doc):
            self.rows.append(dict(doc))

    class _MemDb:
        def __init__(self):
            self.artifacts = _MemColl()

    class _FakeMongo:
        def __init__(self, data_dir: Path):
            self.settings = Settings(data_dir=data_dir)
            self.db = _MemDb()

    store_rows = []
    with tempfile.TemporaryDirectory() as td:
        root_tmp = Path(td)
        store = ArtifactStore(_FakeMongo(root_tmp))
        for mb in (5, 25):
            wav_p = root_tmp / "uploads" / f"sample_{mb}mb.wav"
            wav_p.parent.mkdir(parents=True, exist_ok=True)
            # Write realistic PCM_16 audio bytes matching ~mb MB
            n_samples = int(mb * 1024 * 1024 // 2)
            audio = (np.sin(np.arange(n_samples, dtype=np.float32) * 0.05) * 0.1).astype(np.float32)
            sf.write(wav_p, audio, 16000, subtype="PCM_16")
            actual_mb = round(wav_p.stat().st_size / (1024 * 1024), 2)

            t0 = time.perf_counter()
            rec = store.register(wav_p, "user_bench", resource_id="m_1")
            reg_sec = time.perf_counter() - t0

            t1 = time.perf_counter()
            for _ in range(50):
                resolved = store.resolve(rec)
                assert resolved.is_file()
            res_ms = (time.perf_counter() - t1) * 1000.0 / 50.0
            store_rows.append(
                {
                    "payload_mb": actual_mb,
                    "register_sha256_sec": round(reg_sec, 4),
                    "throughput_mb_per_sec": round(actual_mb / max(reg_sec, 1e-6), 1),
                    "resolve_mean_ms": round(res_ms, 4),
                }
            )

        # 2. Measure FastAPI route construction & non-DB middleware/CORS/validation latency
        app = create_app(Settings(data_dir=root_tmp / "api", web_dist=root_tmp / "no-web"))
        # Call without triggering MongoDB lifespan (since mongod binary is absent on host)
        client = TestClient(app, raise_server_exceptions=False)
        t_orig0 = time.perf_counter()
        bad_origins = 0
        for _ in range(25):
            r = client.post("/api/v1/auth/login", headers={"Origin": "http://evil.invalid"}, json={"username": "a", "password": "b"})
            if r.status_code == 403:
                bad_origins += 1
        origin_ms = (time.perf_counter() - t_orig0) * 1000.0 / 25.0

        t_val0 = time.perf_counter()
        val_errs = 0
        for _ in range(25):
            r = client.post("/api/v1/auth/login", json={})
            if r.status_code == 422:
                val_errs += 1
        val_ms = (time.perf_counter() - t_val0) * 1000.0 / 25.0

        t_notfound0 = time.perf_counter()
        notfound_hits = 0
        for _ in range(25):
            r = client.get("/api/v1/nonexistent-route-probe")
            notfound_hits += int(r.status_code == 404)
        notfound_ms = (time.perf_counter() - t_notfound0) * 1000.0 / 25.0

    return {
        "live_mongod_available": False,
        "note": "Host macOS không cài đặt binary mongod nên không chạy benchmark throughput queue MongoDB trực tiếp; chỉ đo các thành phần backend độc lập (ArtifactStore, FastAPI routing/middleware/validation).",
        "artifact_store": store_rows,
        "http_overhead": {
            "origin_guard_403_hits": bad_origins,
            "origin_guard_mean_ms": round(origin_ms, 3),
            "pydantic_422_hits": val_errs,
            "pydantic_validation_mean_ms": round(val_ms, 3),
            "router_404_hits": notfound_hits,
            "router_404_mean_ms": round(notfound_ms, 3),
        },
    }


def main() -> None:
    setup_root_src()
    t0 = time.perf_counter()
    doc_data = benchmark_doc_ingest_and_schema()
    be_data = benchmark_backend_components()

    out_dir = OUT / "wave3/doc_and_backend"
    write_csv(out_dir / "ingest_summary.csv", doc_data["ingest"])
    write_csv(out_dir / "preview_summary.csv", doc_data["previews"])
    write_csv(out_dir / "schema_mapper_summary.csv", doc_data["schema_mappers"])
    write_json(
        out_dir / "results.json",
        {
            "benchmark": "wave3_doc_ingest_and_backend",
            "elapsed_sec": round(time.perf_counter() - t0, 2),
            "peak_rss_mb": round(rss_mb(), 2),
            **doc_data,
            "backend": be_data,
        },
    )
    log(f"[Wave3B] Done in {time.perf_counter() - t0:.2f}s | peak_rss={rss_mb():.1f}MB")


if __name__ == "__main__":
    main()

