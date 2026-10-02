"""Inspect API behavior and deterministic signal edge cases without changing app data."""

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

from meeting_pipeline.config import load_config
from meeting_pipeline.pipeline.prototype import ActivityRegion, PreparedSource, PrototypePipeline
from meeting_pipeline.pipeline.stages.synchronize import estimate_offset
from meeting_pipeline.web.app import create_app

ROOT = Path("/Users/thien/Documents/School/Luận văn")
OUT = Path("/private/tmp/meeting-demo-review")
OUT.mkdir(parents=True, exist_ok=True)
cfg = load_config(ROOT / "configs/default.yaml")
cfg.paths.data_dir = OUT / "api_test_data"
cfg.paths.model_cache_dir = ROOT / "data/model_cache"
cfg.paths.database_path = OUT / "api_test.sqlite"
client = TestClient(create_app(cfg))
store = client.app.state.demo_jobs
result = {"exports": [], "inputs": [], "checks": []}
for path in (ROOT / "data/demo_jobs").glob("*.json"):
    j = json.loads(path.read_text())
    store.write(j)
    base = "/api/runs/" + j["job_id"]
    for ext in ["json", "csv", "txt", "zip"]:
        r = client.get(base + "/export", params={"format": ext})
        result["exports"].append(
            {"job": j["job_id"], "format": ext, "status": r.status_code, "bytes": len(r.content)}
        )
    seg = json.loads((Path(j["run_dir"]) / "timeline.json").read_text())["segments"][0]
    r = client.get(
        base + "/files/" + seg["processed_clip_artifact_id"], headers={"Range": "bytes=0-99"}
    )
    result["checks"].append(
        {
            "name": "audio_range",
            "job": j["job_id"],
            "status": r.status_code,
            "content_range": r.headers.get("content-range"),
            "bytes": len(r.content),
        }
    )

for label, name, files in [
    ("empty_file", "empty", [("sources", ("empty.wav", b"", "audio/wav"))]),
    ("invalid_audio", "invalid", [("sources", ("not-audio.wav", b"not audio", "audio/wav"))]),
    (
        "too_many_sources",
        "nine",
        [("sources", (f"{i}.wav", b"not audio", "audio/wav")) for i in range(9)],
    ),
]:
    r = client.post("/api/runs", data={"meeting_name": name}, files=files)
    record = {"case": label, "status": r.status_code, "response": r.json()}
    if r.status_code == 202:
        record["job"] = client.get("/api/runs/" + r.json()["job_id"]).json()
    result["inputs"].append(record)

# Only validation tests below stub execution; no mocked result is used for audio quality.
with patch.object(store, "execute"):
    r = client.post(
        "/api/runs",
        data={"meeting_name": "   "},
        files=[("sources", ("x.wav", b"not audio", "audio/wav"))],
    )
    result["inputs"].append(
        {
            "case": "whitespace_name",
            "status": r.status_code,
            "stored_name": store.read(r.json()["job_id"])["meeting_name"],
        }
    )
cfg.audio.max_upload_bytes = 10
r = client.post(
    "/api/runs",
    data={"meeting_name": "oversized"},
    files=[("sources", ("large.wav", b"x" * 11, "audio/wav"))],
)
result["inputs"].append({"case": "oversized", "status": r.status_code})
result["checks"].append(
    {
        "name": "leftover_uploads",
        "files": [
            str(p.relative_to(cfg.paths.data_dir))
            for p in store.upload_root.rglob("*")
            if p.is_file()
        ],
    }
)

stale = {
    "job_id": "stale-running",
    "meeting_name": "stale",
    "status": "running",
    "created_at": "2020-01-01T00:00:00Z",
    "source_paths": [],
}
store.write(stale)
new_app = create_app(cfg)
result["checks"].append(
    {
        "name": "restart_recovery",
        "status_after_recreate": new_app.state.demo_jobs.read("stale-running")["status"],
    }
)

# Current quality heuristics saturate on sufficiently loud signals.
p = PrototypePipeline(cfg)
sr = 16000
t = np.arange(sr) / sr
sources = [
    PreparedSource("a", Path("a.wav"), Path("a.wav"), np.sin(t * 900) * 0.08, "a"),
    PreparedSource("b", Path("b.wav"), Path("b.wav"), np.sin(t * 1500) * 0.5, "b"),
]
e = p._quality_candidates(
    ActivityRegion(0, 1, 1), sources, {s.source_id: s.samples for s in sources}
)
result["checks"].append(
    {
        "name": "different_amplitude_same_quality",
        "features": [[c.speech_presence, c.speech_noise_contrast, c.clipping_avoidance] for c in e],
    }
)

# Validate synchronization against known late recording starts and independent noise.
rng = np.random.default_rng(917)
base = rng.normal(size=sr * 20) * np.repeat(rng.uniform(0.01, 0.2, 200), sr // 10)
for offset in [0.4, 2, 5]:
    est = estimate_offset(base, base[round(sr * offset) :] * 0.7, sr)
    result["checks"].append(
        {"name": "known_start_offset", "expected": offset, "actual": est.mapping.offset_sec}
    )
for seed in range(10):
    r = np.random.default_rng(seed)
    a = r.normal(size=sr * 10) * np.repeat(r.uniform(0.01, 0.2, 100), sr // 10)
    b = r.normal(size=sr * 10) * np.repeat(r.uniform(0.01, 0.2, 100), sr // 10)
    try:
        est = estimate_offset(a, b, sr)
        result["checks"].append(
            {
                "name": "unrelated_signals",
                "seed": seed,
                "accepted": True,
                "offset": est.mapping.offset_sec,
                "peak_ratio": est.peak_ratio,
            }
        )
    except Exception as exc:
        result["checks"].append(
            {"name": "unrelated_signals", "seed": seed, "accepted": False, "error": str(exc)}
        )

# A region spanning a coverage boundary currently has no fully covering source.
sources = [
    PreparedSource("a", Path("a.wav"), Path("a.wav"), np.ones(sr) * 0.1, "a", offset_sec=0),
    PreparedSource("b", Path("b.wav"), Path("b.wav"), np.ones(sr) * 0.1, "b", offset_sec=1),
]
try:
    p._quality_candidates(
        ActivityRegion(0.5, 1.5, 1),
        sources,
        {"a": np.r_[np.ones(sr) * 0.1, np.zeros(sr)], "b": np.r_[np.zeros(sr), np.ones(sr) * 0.1]},
    )
    coverage_error = None
except Exception as exc:
    coverage_error = str(exc)
result["checks"].append(
    {"name": "continuous_speech_across_coverage_boundary", "error": coverage_error}
)

(OUT / "api-and-dsp-audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps(result, ensure_ascii=False, indent=2))
