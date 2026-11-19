"""Shared helpers for the 2026-11-18 benchmark suite against root src/ and configs/."""

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
OUT = ROOT / "reports/benchmark_20261118"
CB_DATA = ROOT / "reports/comparative_benchmark/20261104"
CACHE = ROOT / "data/model_cache"
SEED = 20261118


def setup_root_src(cpu_threads: int = 4) -> None:
    """Ensure root src/ and root configs/ take priority over web_app/."""
    for p in (str(ROOT / "src"), str(ROOT)):
        if p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("MPLCONFIGDIR", str(OUT / "cache/matplotlib"))
    (OUT / "cache/matplotlib").mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    random.seed(SEED)
    import numpy as np

    np.random.seed(SEED)
    try:
        import torch

        torch.manual_seed(SEED)
        torch.set_num_threads(int(os.environ.get("BENCHMARK_CPU_THREADS", str(cpu_threads))))
    except Exception:
        pass


def log(message: str) -> None:
    print(time.strftime("%H:%M:%S"), message, flush=True)


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def rss_mb() -> float:
    val = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return val / (1e6 if sys.platform == "darwin" else 1e3)


def snapshot(model_id: str, revision: str | None = None, *, minutes_hub: bool = False) -> Path:
    hub = (CACHE / "minutes/hub") if minutes_hub else CACHE
    cache = hub / ("models--" + model_id.replace("/", "--"))
    if revision:
        p = cache / "snapshots" / revision
        if p.is_dir():
            return p
    inv_path = CB_DATA / "model_inventory.json"
    if inv_path.is_file():
        for row in read_json(inv_path):
            if row["model_id"] == model_id and row.get("status") == "ready":
                p = Path(row["path"])
                if p.is_dir():
                    return p
    snaps = sorted((cache / "snapshots").glob("*"))
    if snaps:
        return snaps[0]
    raise FileNotFoundError(f"Cached model not found: {model_id}@{revision} in {cache}")


def paired_bootstrap_ci(
    a: list[float], b: list[float], n_boot: int = 5000, seed: int = SEED
) -> dict[str, float]:
    """Paired bootstrap CI for mean(b - a)."""
    import numpy as np

    arr_a = np.asarray(a, dtype=np.float64)
    arr_b = np.asarray(b, dtype=np.float64)
    diff = arr_b - arr_a
    n = len(diff)
    if n == 0:
        return {"n": 0, "mean_diff": 0.0, "ci95_low": 0.0, "ci95_high": 0.0}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    means = diff[idx].mean(axis=1)
    return {
        "n": int(n),
        "mean_a": float(arr_a.mean()),
        "mean_b": float(arr_b.mean()),
        "mean_diff": float(diff.mean()),
        "ci95_low": float(np.percentile(means, 2.5)),
        "ci95_high": float(np.percentile(means, 97.5)),
    }

