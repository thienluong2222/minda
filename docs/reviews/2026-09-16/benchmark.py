"""Reproduce the small ASR and clipping diagnostics recorded in the demo review."""

import json
import os
import random
import time
import unicodedata
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
import numpy as np
import soundfile as sf
import torch
from jiwer import cer, wer

from meeting_pipeline.config import load_config
from meeting_pipeline.pipeline.prototype import PrototypePipeline

ROOT = Path("/Users/thien/Documents/School/Luận văn")
OUT = Path("/private/tmp/meeting-demo-review")
OUT.mkdir(parents=True, exist_ok=True)
cfg = load_config(ROOT / "configs/default.yaml")
cfg.paths.data_dir = OUT / "model_runtime"
cfg.paths.model_cache_dir = ROOT / "data/model_cache"
pipeline = PrototypePipeline(cfg)
torch.set_num_threads(4)
test = ROOT / "data/external/vivos/extracted/vivos/test"
prompts = dict(line.split(maxsplit=1) for line in (test / "prompts.txt").read_text().splitlines())
files = sorted((test / "waves").rglob("*.wav"))
rng = random.Random(20260916)
rng.shuffle(files)
selected = []
speakers = set()
for path in files:
    speaker = path.parent.name
    if speaker not in speakers and 2 <= sf.info(path).duration <= 10:
        speakers.add(speaker)
        selected.append(path)
    if len(selected) == 6:
        break


def normalize(text):
    text = unicodedata.normalize("NFC", text).lower()
    return " ".join(
        "".join(" " if unicodedata.category(c).startswith("P") else c for c in text).split()
    )


results = {
    "seed": 20260916,
    "normalization": (
        "NFC, lowercase, punctuation to spaces, collapse whitespace; retain Vietnamese diacritics"
    ),
    "samples": [],
}
for i, path in enumerate(selected):
    waveform, sr = sf.read(path, dtype="float32")
    assert sr == 16000
    if i == 0:
        sf.write(OUT / "qa-source-a.wav", waveform, 16000)
        sf.write(OUT / "qa-source-b.wav", waveform[6400:] * 0.8, 16000)
        (OUT / "ui-fixture.json").write_text(
            json.dumps(
                {
                    "source_utterance": path.name,
                    "reference": prompts[path.stem],
                    "source_b_expected_offset_sec": 0.4,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    start = time.monotonic()
    with torch.inference_mode():
        hyp = pipeline._transcribe(waveform)
    ref = prompts[path.stem]
    record = {
        "id": path.stem,
        "duration_sec": len(waveform) / sr,
        "reference": ref,
        "hypothesis": hyp,
        "cer": cer(normalize(ref), normalize(hyp)),
        "space_token_error_rate": wer(normalize(ref), normalize(hyp)),
        "elapsed_sec": time.monotonic() - start,
    }
    results["samples"].append(record)
    (OUT / "asr-benchmark.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps(record, ensure_ascii=False), flush=True)
refs = [normalize(s["reference"]) for s in results["samples"]]
hyps = [normalize(s["hypothesis"]) for s in results["samples"]]
results["aggregate"] = {
    "cer": cer(refs, hyps),
    "space_token_error_rate": wer(refs, hyps),
    "audio_seconds": sum(s["duration_sec"] for s in results["samples"]),
}
(OUT / "asr-benchmark.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
print("AGGREGATE", results["aggregate"], flush=True)

# Reproduce an actual saved overlap clip, without modifying its run.
run = ROOT / "data/meetings/real-test-1/runs/6ddaef92-ba05-44a4-ac61-ab6d503cfa36"
segments = json.loads((run / "timeline.json").read_text())["segments"]
segment = next(
    s
    for s in segments
    if s["processed_clip_artifact_id"] == "clips/processed/segment-9-track-1.wav"
)
aligned, sr = sf.read(run / "aligned" / f"{segment['selected_source_id']}.wav", dtype="float32")
mix = aligned[round(segment["start_sec"] * sr) : round(segment["end_sec"] * sr)]
with torch.inference_mode():
    tracks = pipeline._separate(mix)
raw = tracks[0]
stored, _ = sf.read(run / segment["processed_clip_artifact_id"], dtype="float32")
repro = {
    "clip": segment["processed_clip_artifact_id"],
    "raw_peak": float(np.max(np.abs(raw))),
    "raw_over_fullscale_fraction": float(np.mean(np.abs(raw) >= 1)),
    "stored_peak": float(np.max(np.abs(stored))),
    "stored_near_fullscale_fraction": float(np.mean(np.abs(stored) >= 0.999)),
    "max_raw_stored_error": float(np.max(np.abs(raw - stored))),
}
with torch.inference_mode():
    repro["asr_raw"] = pipeline._transcribe(raw)
    repro["asr_stored"] = pipeline._transcribe(stored)
(OUT / "clipping-reproduction.json").write_text(json.dumps(repro, ensure_ascii=False, indent=2))
print("CLIPPING_REPRO", json.dumps(repro, ensure_ascii=False), flush=True)

# The current processor silently truncates a 40-second utterance to 30 seconds.
processor = pipeline._asr_processor
probe = processor(
    np.zeros(16000 * 40, dtype=np.float32),
    sampling_rate=16000,
    return_tensors="pt",
    return_attention_mask=True,
)
long_check = {
    "input_seconds": 40,
    "feature_frames": int(probe.input_features.shape[-1]),
    "processor_chunk_seconds": processor.feature_extractor.chunk_length,
    "configured_max_chunk_seconds": cfg.asr["max_chunk_seconds"],
}
(OUT / "long-input-check.json").write_text(json.dumps(long_check, indent=2))
print("LONG_INPUT", long_check, flush=True)
