"""Paired synthetic Vietnamese line recognition, with exact text known by construction."""

from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.comparative_benchmark.common import (
    OUT,
    ROOT,
    SEED,
    WEB,
    log,
    read_json,
    rss_mb,
    setup,
    sha,
    snapshot,
    write_csv,
    write_json,
)


def prepare():
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    records = [
        json.loads(line) for line in (ROOT / "data/manifests/vivos.jsonl").read_text().splitlines()
    ]
    directory = OUT / "ocr/images"
    directory.mkdir(parents=True, exist_ok=True)
    manifest = []
    fonts = Path("/System/Library/Fonts/Supplemental")
    for split, total in (("validation", 10), ("test", 30)):
        rng = np.random.default_rng(SEED + (1 if split == "test" else 0))
        pool = [
            r for r in records if r["split"] == split and 30 <= len(r["text_normalized"]) <= 120
        ]
        for index, position in enumerate(rng.choice(len(pool), total, replace=False)):
            row = pool[int(position)]
            text = row["text_normalized"]
            if index % 5 == 0:
                text = f"Biểu quyết: {17 + index}/50 đại biểu tán thành, hạn nộp ngày {index % 27 + 1:02d}/11/2026."
            font_name = (
                ("Arial.ttf", "Times New Roman.ttf")[(index % 2)]
                if split == "validation"
                else ("Arial Narrow.ttf", "Times New Roman.ttf", "Courier New.ttf")[index % 3]
            )
            font = ImageFont.truetype(str(fonts / font_name), 32)
            bbox = font.getbbox(text)
            width = bbox[2] - bbox[0] + 40
            height = max(60, bbox[3] - bbox[1] + 28)
            clean = Image.new("RGB", (width, height), "white")
            draw = ImageDraw.Draw(clean)
            draw.text((20, 12 - bbox[1]), text, font=font, fill="black")
            for condition in ("clean", "moderate", "stress"):
                image = clean.copy()
                if condition != "clean":
                    factor = 0.7 if condition == "moderate" else 0.45
                    image = image.resize(
                        (int(width * factor), int(height * factor)), Image.Resampling.LANCZOS
                    )
                    image = image.resize((width, height), Image.Resampling.BICUBIC)
                    image = image.filter(
                        ImageFilter.GaussianBlur(0.25 if condition == "moderate" else 0.65)
                    )
                    if condition == "stress":
                        image = image.rotate(
                            1.2, resample=Image.Resampling.BICUBIC, expand=True, fillcolor="white"
                        )
                    buffer = io.BytesIO()
                    image.save(buffer, format="JPEG", quality=65 if condition == "moderate" else 30)
                    image = Image.open(io.BytesIO(buffer.getvalue())).convert("RGB")
                key = f"{split}_{index:03d}_{condition}"
                path = directory / (key + ".png")
                image.save(path)
                manifest.append(
                    {
                        "id": key,
                        "split": split,
                        "condition": condition,
                        "reference": text,
                        "font": font_name,
                        "origin_id": row["utterance_id"],
                        "path": str(path),
                        "sha256": sha(path),
                        "evidence_type": "rendered_text_exact_ground_truth_not_scanned_real_documents",
                    }
                )
    for index in range(3):
        path = directory / f"blank_{index}.png"
        Image.new("RGB", (800, 64), (255 - index * 20,) * 3).save(path)
        manifest.append(
            {
                "id": f"blank_{index}",
                "split": "test",
                "condition": "blank",
                "reference": "",
                "path": str(path),
                "sha256": sha(path),
                "evidence_type": "negative_control",
            }
        )
    write_json(OUT / "ocr/manifest.json", manifest)
    write_json(
        OUT / "ocr/protocol.json",
        {
            "task": "recognition_on_identical_line_crops",
            "reference": "exact_rendered_string",
            "synthetic_limits": "does_not_validate_page_detection_tables_or_handwriting",
            "models": [
                "tesseract_fast",
                "tesseract_best",
                "easyocr",
                "paddle_latin_v5",
                "vietocr_transformer",
                "vietocr_seq2seq",
            ],
            "tesseract_psm": 7,
            "test_font_variation": True,
            "no_LLM": True,
        },
    )
    log(f"OCR dataset ready: {len(manifest)} images")


def load_recognizer(name):
    import numpy as np
    from PIL import Image

    model_dir = OUT / "ocr/models"
    if name.startswith("tesseract_"):
        directory = (
            WEB / "data/ocr_cache" if name == "tesseract_fast" else model_dir / "tessdata_best"
        )

        def recognize(path):
            result = subprocess.run(
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
                timeout=120,
            )
            return result.stdout.strip()

        return recognize
    if name == "easyocr":
        import easyocr

        model = easyocr.Reader(
            ["vi", "en"],
            gpu=False,
            model_storage_directory=str(model_dir),
            user_network_directory=str(OUT / "runtime/easyocr"),
            download_enabled=False,
            detector=False,
            verbose=False,
        )
        return lambda path: " ".join(
            item[1] for item in model.recognize(np.asarray(Image.open(path).convert("L")), detail=1)
        )
    if name == "paddle_latin_v5":
        from paddleocr import TextRecognition

        model = TextRecognition(
            model_name="latin_PP-OCRv5_mobile_rec",
            model_dir=str(snapshot("PaddlePaddle/latin_PP-OCRv5_mobile_rec")),
            device="cpu",
            enable_mkldnn=False,
            cpu_threads=4,
        )

        def recognize(path):
            result = next(iter(model.predict(input=str(path), batch_size=1)))
            if isinstance(result, dict):
                return str(result["rec_text"])
            value = result.json
            if callable(value):
                value = value()
            return str(value.get("res", value)["rec_text"])

        return recognize
    from vietocr.tool.predictor import Predictor

    config = read_json(
        model_dir
        / ("vgg_transformer.json" if name == "vietocr_transformer" else "vgg_seq2seq.json")
    )
    model = Predictor(config)
    return lambda path: model.predict(Image.open(path).convert("RGB"))


def run(name):
    import jiwer

    from meeting_pipeline.data.vivos import normalize_vietnamese_text

    rows = [r for r in read_json(OUT / "ocr/manifest.json") if r["split"] == "test"]
    start = time.perf_counter()
    recognize = load_recognizer(name)
    load_sec = time.perf_counter() - start
    predictions = []
    for index, row in enumerate(rows):
        started = time.perf_counter()
        try:
            text = recognize(row["path"])
            status = "ok"
            error = None
        except Exception as exc:
            text = ""
            status = "failed"
            error = f"{type(exc).__name__}: {str(exc)[:400]}"
        predictions.append(
            {
                **row,
                "model": name,
                "prediction": text,
                "status": status,
                "error": error,
                "seconds": time.perf_counter() - started,
            }
        )
        if index % 20 == 0:
            log(f"{name} OCR {index}/{len(rows)}")
    destination = OUT / "ocr" / name
    write_json(destination / "predictions.json", predictions)
    summaries = []
    for condition in ("all", "clean", "moderate", "stress", "blank"):
        selected = [r for r in predictions if condition == "all" or r["condition"] == condition]
        refs = [normalize_vietnamese_text(r["reference"]) for r in selected]
        hyps = [normalize_vietnamese_text(r["prediction"]) for r in selected]
        raw_refs = [r["reference"] for r in selected]
        raw_hyps = [r["prediction"] for r in selected]
        summaries.append(
            {
                "model": name,
                "condition": condition,
                "samples": len(selected),
                "cer": jiwer.cer(refs, hyps),
                "wer": jiwer.wer(refs, hyps),
                "raw_cer": jiwer.cer(raw_refs, raw_hyps),
                "exact_match": sum(a == b for a, b in zip(refs, hyps, strict=True)) / len(refs),
                "failure_rate": sum(r["status"] != "ok" for r in selected) / len(selected),
                "total_seconds": sum(r["seconds"] for r in selected),
                "load_sec": load_sec,
                "peak_rss_mb": rss_mb(),
                "blank_hallucinations": sum(
                    bool(r["prediction"].strip()) for r in selected if r["condition"] == "blank"
                ),
            }
        )
    write_json(destination / "summary.json", summaries)
    write_csv(destination / "summary.csv", summaries)
    log(f"{name} OCR CER={summaries[0]['cer']:.4f}")


def main():
    setup()
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "run"])
    parser.add_argument(
        "--model",
        choices=[
            "tesseract_fast",
            "tesseract_best",
            "easyocr",
            "paddle_latin_v5",
            "vietocr_transformer",
            "vietocr_seq2seq",
        ],
    )
    args = parser.parse_args()
    prepare() if args.command == "prepare" else run(args.model)


if __name__ == "__main__":
    main()
