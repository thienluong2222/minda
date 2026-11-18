"""Execute independent CPU components in separate, bounded-memory processes."""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.comparative_benchmark.common import (
    OUT,
    ROOT,
    log,
    read_json,
    verify_production_unchanged,
    write_json,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stages",
        nargs="+",
        choices=["segmentation", "ocr", "text", "separation", "algorithms"],
        required=True,
    )
    args = parser.parse_args()
    jobs = []
    if "segmentation" in args.stages:
        jobs += [
            ("segmentation", name, ["segmentation", "run", "--model", name])
            for name in (
                "pyannote3",
                "silero",
                "crdnn",
                "fsmn",
                "diarizen_base",
                "diarizen_large",
                "diarizen_v2",
            )
        ]
    if "ocr" in args.stages:
        jobs += [
            ("ocr", name, ["ocr", "run", "--model", name])
            for name in (
                "tesseract_fast",
                "tesseract_best",
                "easyocr",
                "paddle_latin_v5",
                "vietocr_transformer",
                "vietocr_seq2seq",
            )
        ]
    if "algorithms" in args.stages:
        jobs += [
            ("algorithms", name, ["algorithms", name]) for name in ("speaker-clustering", "fusion")
        ]
    if "text" in args.stages:
        jobs += [
            ("text", name, ["text", "run", "--encoder", name])
            for name in ("e5_small", "e5_base", "minilm", "bge_m3")
        ]
    if "separation" in args.stages:
        jobs += [
            ("separation", name, ["separation", "run", "--model", name])
            for name in ("sepformer_whamr", "sepformer_wham", "sepformer_libri2mix", "convtasnet")
        ]
    tag = "_".join(args.stages)
    status_file = OUT / f"components_{tag}_status.json"
    status = []
    for stage, name, arguments in jobs:
        # Avoid loading multiple large ASR/embedding/separation models into 16GB.
        if stage in ("text", "separation"):
            while True:
                path = OUT / "asr_mps_float16/suite_status.json"
                rows = read_json(path) if path.exists() else []
                if len(rows) >= 5 and all(r["status"] in ("completed", "failed") for r in rows):
                    break
                time.sleep(5)
        record = {"stage": stage, "model": name, "status": "running", "started_unix": time.time()}
        status.append(record)
        write_json(status_file, status)
        log(f"Start {stage}/{name}")
        module = "experiments.comparative_benchmark." + arguments[0]
        with (OUT / f"{stage}_{name}.log").open("a") as handle:
            result = subprocess.run(
                [sys.executable, "-B", "-u", "-m", module, *arguments[1:]],
                cwd=ROOT,
                stdout=handle,
                stderr=subprocess.STDOUT,
            )
        record.update(
            status="completed" if result.returncode == 0 else "failed",
            exit_code=result.returncode,
            finished_unix=time.time(),
        )
        write_json(status_file, status)
        assert verify_production_unchanged()["passed"]
        from experiments.comparative_benchmark.reviews import refresh

        refresh()
        log(f"Finished {stage}/{name}: {record['status']}")


if __name__ == "__main__":
    main()
