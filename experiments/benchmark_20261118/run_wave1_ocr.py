"""Wave 1-4: OCR benchmark — single-line (--psm 7) and full A4 page + administrative table (OpenCV + --psm 3 / VietOCR)."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CB_DATA, OUT, ROOT, SEED, log, read_json, rss_mb, setup_root_src, write_csv, write_json


def load_single_line_recognizer(name: str):
    import numpy as np
    from PIL import Image

    model_dir = CB_DATA / "ocr/models"
    if name.startswith("tesseract_"):
        directory = (
            (ROOT / "data/ocr_cache") if name == "tesseract_fast" else (model_dir / "tessdata_best")
        )

        def recognize(path: Path) -> str:
            res = subprocess.run(
                [
                    "tesseract",
                    str(path),
                    "stdout",
                    "--tessdata-dir",
                    str(directory),
                    "-l",
                    "vie+eng",
                    "--psm",
                    "7",
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=60,
            )
            return res.stdout.strip()

        return recognize

    if name == "easyocr":
        import easyocr

        reader = easyocr.Reader(
            ["vi", "en"],
            gpu=False,
            model_storage_directory=str(model_dir),
            download_enabled=False,
            detector=False,
            verbose=False,
        )
        return lambda path: " ".join(
            item[1] for item in reader.recognize(np.asarray(Image.open(path).convert("L")), detail=1)
        )

    from vietocr.tool.predictor import Predictor

    cfg = read_json(
        model_dir / ("vgg_transformer.json" if name == "vietocr_transformer" else "vgg_seq2seq.json")
    )
    cfg["device"] = "cpu"
    predictor = Predictor(cfg)
    return lambda path: predictor.predict(Image.open(path).convert("RGB"))


def benchmark_single_line() -> tuple[list[dict], dict]:
    import jiwer
    from meeting_pipeline.data.vivos import normalize_vietnamese_text

    rows = [r for r in read_json(CB_DATA / "ocr/manifest.json") if r["split"] == "test"]
    engines = ["tesseract_fast", "tesseract_best", "easyocr", "vietocr_seq2seq", "vietocr_transformer"]
    summaries = []
    per_engine_meta = {}

    for eng in engines:
        log(f"[OCR Line] Running {eng} on {len(rows)} test line images...")
        t0 = time.perf_counter()
        rec = load_single_line_recognizer(eng)
        load_sec = time.perf_counter() - t0
        preds = []
        t_inf = time.perf_counter()
        for r in rows:
            s0 = time.perf_counter()
            try:
                txt = rec(Path(r["path"]))
                status = "ok"
            except Exception as exc:
                txt = ""
                status = f"err:{type(exc).__name__}"
            preds.append({**r, "prediction": txt, "status": status, "sec": time.perf_counter() - s0})
        inf_sec = time.perf_counter() - t_inf
        per_engine_meta[eng] = {"load_sec": round(load_sec, 3), "infer_sec": round(inf_sec, 3)}

        for cond in ("all", "clean", "moderate", "stress", "blank"):
            sel = [p for p in preds if cond == "all" or p["condition"] == cond]
            refs = [normalize_vietnamese_text(p["reference"]) for p in sel]
            hyps = [normalize_vietnamese_text(p["prediction"]) for p in sel]
            raw_refs = [p["reference"] for p in sel]
            raw_hyps = [p["prediction"] for p in sel]
            summaries.append(
                {
                    "engine": eng,
                    "condition": cond,
                    "samples": len(sel),
                    "cer": round(float(jiwer.cer(refs, hyps)), 4),
                    "wer": round(float(jiwer.wer(refs, hyps)), 4),
                    "raw_cer": round(float(jiwer.cer(raw_refs, raw_hyps)), 4),
                    "exact_match": round(
                        sum(a == b for a, b in zip(refs, hyps, strict=True)) / max(len(refs), 1), 4
                    ),
                    "blank_hallucinations": sum(bool(p["prediction"].strip()) for p in sel if p["condition"] == "blank"),
                    "total_sec": round(sum(p["sec"] for p in sel), 2),
                }
            )
    return summaries, per_engine_meta


def render_full_page_table_dataset(out_dir: Path) -> list[dict]:
    """Render 18 realistic Vietnamese administrative A4 pages (6 base pages x 3 conditions) with ruled tables."""
    import json as _json
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    out_dir.mkdir(parents=True, exist_ok=True)
    fonts_dir = Path("/System/Library/Fonts/Supplemental")
    font_bold = ImageFont.truetype(str(fonts_dir / "Times New Roman Bold.ttf"), 24)
    font_reg = ImageFont.truetype(str(fonts_dir / "Times New Roman.ttf"), 22)
    font_tbl = ImageFont.truetype(str(fonts_dir / "Times New Roman.ttf"), 20)

    v21_cases = [
        _json.loads(l)
        for l in (ROOT / "artifacts/graph-synthetic-v2.1/test/references/cases.jsonl").read_text().splitlines()
        if l.strip()
    ][:6]

    pages = []
    for idx, case in enumerate(v21_cases):
        title = f"BIÊN BẢN CUỘC HỌP SỐ {idx + 10}/2026"
        meta_line = f"Hôm nay ngày {12 + idx:02d}/11/2026, lúc 14h30 tại Phòng họp A{idx + 1}."
        para1 = "Chủ tọa: Nguyễn Văn An. Thư ký: Trần Thị Bình."
        # Build 4x5 assignment table (header + 4 rows) from turns
        turns = case["turns"][:4]
        table_rows = [
            ["STT", "Người phụ trách", "Nội dung phân công", "Thời hạn"],
        ]
        for r_i, t in enumerate(turns, 1):
            spk = t["speaker"]
            txt = t["text"][:48].rstrip(" ,.")
            table_rows.append([str(r_i), spk, txt, f"{18 + r_i:02d}/11/2026"])

        W, H = 1240, 1754  # ~150 DPI A4
        clean = Image.new("RGB", (W, H), "white")
        draw = ImageDraw.Draw(clean)
        y = 80
        draw.text((280, y), "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", font=font_bold, fill="black")
        y += 38
        draw.text((380, y), "Độc lập - Tự do - Hạnh phúc", font=font_reg, fill="black")
        y += 60
        draw.text((400, y), title, font=font_bold, fill="black")
        y += 52
        draw.text((90, y), meta_line, font=font_reg, fill="black")
        y += 40
        draw.text((90, y), para1, font=font_reg, fill="black")
        y += 55
        draw.text((90, y), "Bảng tổng hợp phân công công việc:", font=font_bold, fill="black")
        y += 42

        # Draw bordered table
        col_x = [90, 170, 390, 960, 1150]
        row_h = 64
        x0, x1 = col_x[0], col_x[-1]
        y0 = y
        y1 = y0 + row_h * len(table_rows)
        for r_i, row in enumerate(table_rows):
            ry = y0 + r_i * row_h
            draw.line([(x0, ry), (x1, ry)], fill="black", width=2)
            for c_i, cell_text in enumerate(row):
                draw.text((col_x[c_i] + 10, ry + 18), cell_text, font=font_bold if r_i == 0 else font_tbl, fill="black")
        draw.line([(x0, y1), (x1, y1)], fill="black", width=2)
        for cx in col_x:
            draw.line([(cx, y0), (cx, y1)], fill="black", width=2)

        full_text_ref = "\n".join(
            [
                "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM",
                "Độc lập - Tự do - Hạnh phúc",
                title,
                meta_line,
                para1,
                "Bảng tổng hợp phân công công việc:",
                *[" ".join(r) for r in table_rows],
            ]
        )

        for cond in ("clean", "moderate", "stress"):
            img = clean.copy()
            if cond != "clean":
                factor = 0.78 if cond == "moderate" else 0.58
                img = img.resize((int(W * factor), int(H * factor)), Image.Resampling.LANCZOS)
                img = img.resize((W, H), Image.Resampling.BICUBIC)
                img = img.filter(ImageFilter.GaussianBlur(0.2 if cond == "moderate" else 0.55))
                if cond == "stress":
                    img = img.rotate(1.2, resample=Image.Resampling.BICUBIC, expand=False, fillcolor="white")
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=75 if cond == "moderate" else 40)
                img = Image.open(io.BytesIO(buf.getvalue())).convert("RGB")
            img_path = out_dir / f"page_{idx:02d}_{cond}.png"
            img.save(img_path)
            pages.append(
                {
                    "id": f"page_{idx:02d}_{cond}",
                    "condition": cond,
                    "path": str(img_path),
                    "full_text_ref": full_text_ref,
                    "table_rows_ref": table_rows,
                }
            )
    return pages


def benchmark_full_page_and_table(pages: list[dict]) -> list[dict]:
    import cv2
    import itertools
    import jiwer
    import numpy as np
    import pytesseract
    from PIL import Image
    from meeting_backend.processing.documents.ocr import clusters, extract_image
    from meeting_pipeline.data.vivos import normalize_vietnamese_text
    from vietocr.tool.predictor import Predictor

    tess_fast = ROOT / "data/ocr_cache"
    tess_best = CB_DATA / "ocr/models/tessdata_best"
    v_cfg = read_json(CB_DATA / "ocr/models/vgg_transformer.json")
    v_cfg["device"] = "cpu"
    vietocr_pred = Predictor(v_cfg)

    results = []
    with tempfile.TemporaryDirectory() as td:
        rep_dir = Path(td)
        modes = [
            "raw_tess_fast_psm3",
            "raw_tess_best_psm3",
            "prod_opencv_tess_fast",
            "prod_opencv_tess_best",
            "opencv_cells_vietocr",
        ]
        for mode in modes:
            log(f"[OCR Page/Table] Evaluating {mode} on {len(pages)} A4 pages...")
            per_cond = {c: [] for c in ("clean", "moderate", "stress")}
            all_rows = []
            for p in pages:
                img = Image.open(p["path"]).convert("RGB")
                t0 = time.perf_counter()
                ref_cells = [normalize_vietnamese_text(c) for row in p["table_rows_ref"] for c in row]
                page_ref = normalize_vietnamese_text(p["full_text_ref"])

                if mode.startswith("raw_tess_"):
                    cdir = tess_fast if mode.endswith("fast_psm3") else tess_best
                    text = pytesseract.image_to_string(
                        img, lang="vie+eng", config=f'--tessdata-dir "{cdir}" --psm 3', timeout=60
                    )
                    page_hyp = normalize_vietnamese_text(text)
                    table_detected = False
                    cell_cer = None
                    cell_em = 0.0
                elif mode.startswith("prod_opencv_"):
                    cdir = tess_fast if mode.endswith("tess_fast") else tess_best
                    elements, _ = extract_image(img, cdir, rep_dir / f"{p['id']}_{mode}.json")
                    chunks = []
                    pred_cells = []
                    for el in elements:
                        if el["type"] == "table":
                            chunks.extend(" ".join(r) for r in el["rows"])
                            pred_cells.extend(normalize_vietnamese_text(c) for r in el["rows"] for c in r)
                        else:
                            chunks.append(el["text"])
                    page_hyp = normalize_vietnamese_text("\n".join(chunks))
                    table_detected = any(el["type"] == "table" for el in elements)
                    if pred_cells and len(pred_cells) == len(ref_cells):
                        cell_cer = float(jiwer.cer(ref_cells, pred_cells))
                        cell_em = sum(a == b for a, b in zip(ref_cells, pred_cells, strict=True)) / len(ref_cells)
                    else:
                        # Table missed or grid dimension mismatch -> measure against joined table ref string
                        tbl_ref_s = " ".join(ref_cells)
                        tbl_hyp_s = " ".join(pred_cells)
                        cell_cer = float(jiwer.cer([tbl_ref_s], [tbl_hyp_s])) if pred_cells else 1.0
                        cell_em = 0.0
                else:
                    # OpenCV ruled table detection + VietOCR per cell; page text falls back to tess_best paragraphs
                    elements, _ = extract_image(img, tess_best, rep_dir / f"{p['id']}_grid.json")
                    gray = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2GRAY)
                    mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
                    horizontal = cv2.morphologyEx(
                        mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, img.width // 25), 1))
                    )
                    vertical = cv2.morphologyEx(
                        mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, img.height // 25)))
                    )
                    contours, _ = cv2.findContours(cv2.add(horizontal, vertical), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    pred_cells = []
                    table_detected = False
                    for cnt in contours:
                        x, y, w, h = cv2.boundingRect(cnt)
                        if w < img.width * 0.25 or h < 50:
                            continue
                        xs = clusters(np.where((vertical[y : y + h, x : x + w] > 0).sum(axis=0) > h * 0.65)[0])
                        ys = clusters(np.where((horizontal[y : y + h, x : x + w] > 0).sum(axis=1) > w * 0.65)[0])
                        if not 2 <= len(xs) <= 15 or not 2 <= len(ys) <= 100:
                            continue
                        table_detected = True
                        xs = [x + i for i in xs]
                        ys = [y + i for i in ys]
                        for top, bottom in itertools.pairwise(ys):
                            for left, right in itertools.pairwise(xs):
                                crop = img.crop((max(0, left + 2), max(0, top + 2), max(left + 4, right - 2), max(top + 4, bottom - 2)))
                                pred_cells.append(normalize_vietnamese_text(vietocr_pred.predict(crop)))
                        break
                    para_txt = "\n".join(el["text"] for el in elements if el["type"] == "paragraph")
                    page_hyp = normalize_vietnamese_text(para_txt + " " + " ".join(pred_cells))
                    if pred_cells and len(pred_cells) == len(ref_cells):
                        cell_cer = float(jiwer.cer(ref_cells, pred_cells))
                        cell_em = sum(a == b for a, b in zip(ref_cells, pred_cells, strict=True)) / len(ref_cells)
                    else:
                        tbl_ref_s = " ".join(ref_cells)
                        tbl_hyp_s = " ".join(pred_cells)
                        cell_cer = float(jiwer.cer([tbl_ref_s], [tbl_hyp_s])) if pred_cells else 1.0
                        cell_em = 0.0

                dt = time.perf_counter() - t0
                row = {
                    "page_id": p["id"],
                    "condition": p["condition"],
                    "page_cer": float(jiwer.cer([page_ref], [page_hyp])),
                    "page_wer": float(jiwer.wer([page_ref], [page_hyp])),
                    "table_detected": int(table_detected),
                    "cell_cer": cell_cer,
                    "cell_exact_match": cell_em,
                    "seconds": dt,
                }
                per_cond[p["condition"]].append(row)
                all_rows.append(row)

            for cond, subset in [("all", all_rows), *per_cond.items()]:
                cell_cers = [r["cell_cer"] for r in subset if r["cell_cer"] is not None]
                results.append(
                    {
                        "mode": mode,
                        "condition": cond,
                        "pages": len(subset),
                        "page_cer": round(float(np.mean([r["page_cer"] for r in subset])), 4),
                        "page_wer": round(float(np.mean([r["page_wer"] for r in subset])), 4),
                        "table_detect_rate": round(float(np.mean([r["table_detected"] for r in subset])), 4)
                        if not mode.startswith("raw_tess_")
                        else None,
                        "table_cell_cer": round(float(np.mean(cell_cers)), 4) if cell_cers else None,
                        "table_cell_exact_match": round(float(np.mean([r["cell_exact_match"] for r in subset])), 4)
                        if not mode.startswith("raw_tess_")
                        else None,
                        "avg_sec_per_page": round(float(np.mean([r["seconds"] for r in subset])), 3),
                    }
                )
    return results


def main() -> None:
    setup_root_src()
    t0 = time.perf_counter()
    line_summary, line_meta = benchmark_single_line()
    pages_dir = OUT / "wave1/ocr/pages"
    pages = render_full_page_table_dataset(pages_dir)
    page_summary = benchmark_full_page_and_table(pages)

    out_dir = OUT / "wave1/ocr"
    write_csv(out_dir / "line_summary.csv", line_summary)
    write_csv(out_dir / "page_table_summary.csv", page_summary)
    write_json(
        out_dir / "results.json",
        {
            "benchmark": "wave1_ocr",
            "elapsed_sec": round(time.perf_counter() - t0, 2),
            "peak_rss_mb": round(rss_mb(), 2),
            "line_meta": line_meta,
            "line_summary": line_summary,
            "page_table_summary": page_summary,
        },
    )
    log(f"[OCR] Done in {time.perf_counter() - t0:.2f}s")


if __name__ == "__main__":
    main()

