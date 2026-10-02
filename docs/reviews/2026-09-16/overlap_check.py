"""Run an easy two-speaker overlap diagnostic after benchmark.py has selected samples."""

import json
import os
import time
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
import numpy as np
import soundfile as sf
import torch

from meeting_pipeline.config import load_config
from meeting_pipeline.pipeline.prototype import PrototypePipeline

root = Path("/Users/thien/Documents/School/Luận văn")
out = Path("/private/tmp/meeting-demo-review")
out.mkdir(parents=True, exist_ok=True)
samples = json.loads((out / "asr-benchmark.json").read_text())["samples"][:2]
waves = []
for s in samples:
    path = next((root / "data/external/vivos/extracted/vivos/test/waves").rglob(s["id"] + ".wav"))
    x, sr = sf.read(path, dtype="float32")
    x = x * (0.08 / np.sqrt(np.mean(x * x)))
    waves.append(x)
starts = [0.5, 1.5]
total = round((max(t + len(x) / sr for t, x in zip(starts, waves, strict=True)) + 0.5) * sr)
clean = []
for i, (t, x) in enumerate(zip(starts, waves, strict=True)):
    a = np.zeros(total, dtype="float32")
    a[round(t * sr) : round(t * sr) + len(x)] = x
    clean.append(a)
    sf.write(out / f"overlap-clean-{i + 1}.wav", a, sr, subtype="FLOAT")
mixtures = [clean[0] + 0.45 * clean[1], 0.45 * clean[0] + clean[1]]
paths = []
for i, x in enumerate(mixtures):
    path = out / f"overlap-mic-{i + 1}.wav"
    sf.write(path, x, sr, subtype="FLOAT")
    paths.append(path)
cfg = load_config(root / "configs/default.yaml")
cfg.paths.data_dir = out / "synthetic_data"
cfg.paths.model_cache_dir = root / "data/model_cache"
torch.set_num_threads(4)
start = time.monotonic()
with torch.inference_mode():
    run = PrototypePipeline(cfg).run("controlled-two-speaker-overlap", paths)
segments = json.loads((run / "timeline.json").read_text())["segments"]
result = {
    "description": (
        "Easy diagnostic: two real VIVOS utterances mixed at known gains, "
        "no room reverberation/noise/drift. Not representative meeting benchmark. "
        "Utterance windows include source silence."
    ),
    "duration_sec": total / sr,
    "reference": [
        dict(s, start_sec=t, end_sec=t + s["duration_sec"])
        for t, s in zip(starts, samples, strict=True)
    ],
    "elapsed_sec": time.monotonic() - start,
    "run_dir": str(run),
    "segments": [
        dict(
            start=s["start_sec"],
            end=s["end_sec"],
            text=s["text"],
            overlap=s["overlap_group_id"] is not None,
            source=s["selected_source_id"],
            track=s["track_id"],
        )
        for s in segments
    ],
}
(out / "controlled-overlap.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps(result, ensure_ascii=False, indent=2))
