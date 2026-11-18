"""Sequential model processes keep RAM bounded and preserve uncached timing."""

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
    verify_production_unchanged,
    write_json,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=["cpu", "mps"], default="cpu")
    parser.add_argument("--dtype", choices=["float32", "float16"], default="float32")
    args = parser.parse_args()
    group = (
        "asr"
        if args.device == "cpu"
        else "asr_mps"
        if args.dtype == "float32"
        else "asr_mps_float16"
    )
    status = []
    for model in (
        "phowhisper_small",
        "phowhisper_medium",
        "whisper_turbo",
        "wav2vec2_vi",
        "phowhisper_large",
    ):
        record = {"model": model, "status": "running", "started_unix": time.time()}
        status.append(record)
        write_json(OUT / group / "suite_status.json", status)
        for split in ("synthetic_validation", "synthetic_test"):
            log(f"Start {model}/{split}")
            with (OUT / f"{group}_{model}_{split}.log").open("a") as handle:
                completed = subprocess.run(
                    [
                        str(ROOT / ".venv/bin/python"),
                        "-B",
                        "-u",
                        "-m",
                        "experiments.comparative_benchmark.asr",
                        "run",
                        "--model",
                        model,
                        "--split",
                        split,
                        "--device",
                        args.device,
                        "--dtype",
                        args.dtype,
                    ],
                    cwd=ROOT,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                )
            record[split + "_exit_code"] = completed.returncode
            if completed.returncode:
                record["status"] = "failed"
                break
        else:
            record["status"] = "completed"
        record["finished_unix"] = time.time()
        write_json(OUT / group / "suite_status.json", status)
        assert verify_production_unchanged()["passed"]
        # Reviews are refreshed after each completed model, without running an LLM.
        from experiments.comparative_benchmark.reviews import refresh

        refresh()
        log(f"Finished {model}: {record['status']}")


if __name__ == "__main__":
    main()
