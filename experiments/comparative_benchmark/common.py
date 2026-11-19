"""Shared experiment storage and metrics; no production configuration mutations."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import random
import resource
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT
OUT = ROOT / "reports/comparative_benchmark/20261104"
CACHE = ROOT / "data/model_cache"
SEED = 20261104


def setup() -> None:
    """Use the current web core, fixed seeds, and bounded CPU resources."""
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(WEB / "src"))
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("MPLCONFIGDIR", str(OUT / "runtime/matplotlib"))
    os.environ.setdefault("XDG_CACHE_HOME", str(OUT / "runtime/cache"))
    os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(OUT / "runtime/paddlex"))
    random.seed(SEED)
    import numpy as np
    import torch

    np.random.seed(SEED)
    torch.manual_seed(SEED)
    torch.set_num_threads(int(os.environ.get("BENCHMARK_CPU_THREADS", "4")))
    OUT.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rss_mb() -> float:
    # macOS ru_maxrss is in bytes; Linux reports KiB.
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value / (1e6 if sys.platform == "darwin" else 1e3)


def log(message: str) -> None:
    print(time.strftime("%H:%M:%S"), message, flush=True)


def snapshot(model_id: str, revision: str | None = None) -> Path:
    cache = CACHE / ("models--" + model_id.replace("/", "--"))
    if revision:
        path = cache / "snapshots" / revision
        if path.is_dir():
            return path
    inventory = OUT / "model_inventory.json"
    if inventory.exists():
        for record in read_json(inventory):
            if record["model_id"] == model_id and record.get("status") == "ready":
                return Path(record["path"])
    candidates = sorted((cache / "snapshots").glob("*"))
    if len(candidates) == 1:
        return candidates[0]
    raise FileNotFoundError(f"Exact snapshot not available: {model_id}@{revision}")


def verify_production_unchanged() -> dict[str, Any]:
    baseline = read_json(OUT / "baseline_manifest.json")
    changed = []
    for name, expected in baseline["source_files"].items():
        kind, relative = name.split("/", 1)
        path = (WEB if kind == "web" else ROOT) / relative
        if not path.is_file() or sha(path) != expected:
            changed.append(name)
    result = {
        "passed": not changed,
        "checked_files": len(baseline["source_files"]),
        "changed": changed,
    }
    write_json(OUT / "production_integrity.json", result)
    return result
