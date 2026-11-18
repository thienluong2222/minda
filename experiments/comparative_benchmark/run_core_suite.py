"""Run unchanged-core smoke replays after the memory-heavy component suite."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.comparative_benchmark.common import OUT, ROOT, log, read_json, write_json


def main():
    path = OUT / "components_text_separation_status.json"
    while True:
        rows = read_json(path) if path.exists() else []
        if len(rows) == 8 and all(r["status"] in ("completed", "failed") for r in rows):
            break
        time.sleep(5)
    status = []
    for configuration in ("baseline", "calibrated_ecapa", "wespeaker", "selected_asr"):
        row = {"configuration": configuration, "status": "running"}
        status.append(row)
        write_json(OUT / "core_replay/suite_status.json", status)
        log(f"Start core/{configuration}")
        with (OUT / f"core_{configuration}.log").open("a") as handle:
            result = subprocess.run(
                [
                    str(ROOT / ".venv/bin/python"),
                    "-B",
                    "-u",
                    "-m",
                    "experiments.comparative_benchmark.core_replay",
                    "--configuration",
                    configuration,
                ],
                cwd=ROOT,
                stdout=handle,
                stderr=subprocess.STDOUT,
            )
        row.update(
            status="completed" if result.returncode == 0 else "failed", exit_code=result.returncode
        )
        write_json(OUT / "core_replay/suite_status.json", status)
        log(f"Finished core/{configuration}: {row['status']}")


if __name__ == "__main__":
    main()
