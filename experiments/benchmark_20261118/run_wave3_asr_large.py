"""Wave 3D: Heavy ASR models (PhoWhisper-large MLX, whisper-large-v3-turbo MLX, wav2vec2-base-vietnamese-250h)."""

from __future__ import annotations

import csv
import dataclasses
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CB_DATA, CACHE, OUT, ROOT, log, paired_bootstrap_ci, read_json, rss_mb, setup_root_src, write_csv, write_json


def convert_to_tmp_mlx(model_id: str, revision: str, out_dir: Path) -> Path:
    """Convert local HuggingFace Whisper checkpoint to temporary MLX float16 directory using reviewed converter."""
    snap = CACHE / ("models--" + model_id.replace("/", "--")) / "snapshots" / revision
    converter = ROOT / "data/runtime/asr_mlx/convert_upstream.py"
    expected_sha = "1f1de41ac5d3faeb241bcea97a3f99c760b802cd92e02715699c17b5658f5cb2"
    if hashlib.sha256(converter.read_bytes()).hexdigest() != expected_sha:
        raise ValueError("Unexpected convert_upstream.py SHA-256")
    out_dir.mkdir(parents=True, exist_ok=True)
    # Run inside .venv-asr-mlx where mlx + mlx_whisper live
    script = f"""
import dataclasses, hashlib, importlib.util, json
from pathlib import Path
import mlx.core as mx
from mlx.utils import tree_flatten
spec = importlib.util.spec_from_file_location("cvt", {str(converter)!r})
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
model = mod.convert({str(snap)!r}, mx.float16)
out = Path({str(out_dir)!r})
mx.save_safetensors(str(out / "weights.safetensors"), dict(tree_flatten(model.parameters())))
(out / "config.json").write_text(json.dumps(dataclasses.asdict(model.dims)))
gen = json.loads((Path({str(snap)!r}) / "generation_config.json").read_text())
manifest = {{
    "model_id": {model_id!r},
    "revision": {revision!r},
    "dtype": "float16",
    "converter_sha256": {expected_sha!r},
    "alignment_heads": gen["alignment_heads"],
    "weights_sha256": hashlib.sha256((out / "weights.safetensors").read_bytes()).hexdigest(),
}}
(out / "conversion.json").write_text(json.dumps(manifest, indent=2))
print("CONVERTED", out)
"""
    subprocess.run([str(ROOT / ".venv-asr-mlx/bin/python"), "-c", script], check=True)
    return out_dir


def eval_adapter(adapter, rows: list[dict], label: str) -> tuple[list[dict], dict]:
    import jiwer
    import soundfile as sf

    from meeting_pipeline.data.vivos import normalize_vietnamese_text

    preds = []
    confs = []
    audio_sec = 0.0
    non_tr = 0
    t0 = time.perf_counter()
    for idx, r in enumerate(rows):
        w, sr = sf.read(r["path"], dtype="float32")
        if w.ndim > 1:
            w = w[:, 0]
        audio_sec += len(w) / sr
        s0 = time.perf_counter()
        res = adapter.transcribe(w, sr)
        dt = time.perf_counter() - s0
        hyp = normalize_vietnamese_text(res.text)
        ref = normalize_vietnamese_text(r["reference"])
        wer = float(jiwer.wer([ref], [hyp])) if ref else (0.0 if not hyp else 1.0)
        cer = float(jiwer.cer([ref], [hyp])) if ref else (0.0 if not hyp else 1.0)
        wcs = [wd.confidence for wd in res.words if wd.confidence is not None]
        mc = float(sum(wcs) / len(wcs)) if wcs else None
        if mc is not None:
            confs.append(mc)
        if res.status != "transcribed":
            non_tr += 1
        preds.append(
            {
                "id": r["id"],
                "split": r.get("split", "all"),
                "condition": r.get("condition", "clean"),
                "ref_norm": ref,
                "hyp_norm": hyp,
                "wer": wer,
                "cer": cer,
                "status": res.status,
                "seconds": round(dt, 4),
            }
        )
        if (idx + 1) % 100 == 0:
            log(f"[Wave3D ASR {label}] {idx + 1}/{len(rows)} ({time.perf_counter() - t0:.1f}s)")

    wall = time.perf_counter() - t0
    refs = [p["ref_norm"] for p in preds]
    hyps = [p["hyp_norm"] for p in preds]
    return preds, {
        "label": label,
        "samples": len(preds),
        "audio_sec": round(audio_sec, 2),
        "wall_sec": round(wall, 2),
        "rtf": round(wall / max(audio_sec, 1e-6), 4),
        "corpus_wer": round(float(jiwer.wer(refs, hyps)), 4),
        "corpus_cer": round(float(jiwer.cer(refs, hyps)), 4),
        "non_transcribed": non_tr,
        "mean_word_confidence": round(float(sum(confs) / len(confs)), 4) if confs else None,
        "confidence_coverage": round(len(confs) / max(len(preds), 1), 4),
    }


def make_wav2vec2_adapter(snap: Path):
    import numpy as np
    import torch
    from transformers import AutoModelForCTC, AutoProcessor

    from meeting_pipeline.adapters.phowhisper_asr import AsrResult, BaseAsrAdapter

    processor = AutoProcessor.from_pretrained(snap, local_files_only=True)
    model = AutoModelForCTC.from_pretrained(snap, local_files_only=True).to(torch.device("cpu")).eval()

    class Wav2Vec2Adapter(BaseAsrAdapter):
        def transcribe(self, signal: np.ndarray, sample_rate: int = 16000) -> AsrResult:
            inputs = processor(signal, sampling_rate=sample_rate, return_tensors="pt")
            with torch.inference_mode():
                logits = model(inputs.input_values).logits
            pred_ids = torch.argmax(logits, dim=-1)
            text = processor.batch_decode(pred_ids)[0].strip()
            return AsrResult(text=text, words=[], status="transcribed" if text else "non_transcribed", warnings=[])

    return Wav2Vec2Adapter()


def main() -> None:
    setup_root_src()
    from meeting_pipeline.adapters.phowhisper_asr import PhoWhisperAsrAdapter
    from meeting_pipeline.config import load_config

    t0 = time.perf_counter()
    asr_manifest = read_json(CB_DATA / "asr/manifest.json")
    manifest136 = [dict(r, path=r["audio_path"]) for r in asr_manifest if r["split"] in {"test", "synthetic_test"}]
    vivos = [json.loads(l) for l in (ROOT / "data/manifests/vivos.jsonl").read_text().splitlines() if l.strip()]
    vivos563 = [
        {"id": r["utterance_id"], "split": "vivos_test_563", "condition": "clean", "path": str(ROOT / r["audio_path"]), "reference": r["text_normalized"]}
        for r in vivos
        if r["split"] == "test" and not r.get("is_enrollment")
    ]

    cfg_base = load_config(ROOT / "configs/default.yaml").asr
    out_dir = OUT / "wave3/asr_large"
    out_dir.mkdir(parents=True, exist_ok=True)
    summaries = []
    vivos_preds_by_model = {}

    whisper_specs = [
        ("phowhisper_large_mlx", "vinai/PhoWhisper-large", "b9136a44b5f2ca664bd0b8f74baecf1715f6eeeb"),
        ("whisper_turbo_mlx", "openai/whisper-large-v3-turbo", "41f01f3fe87f28c78e2fbf8b568835947dd65ed9"),
    ]
    with tempfile.TemporaryDirectory(prefix="wave3-asr-mlx-") as td:
        for key, mid, rev in whisper_specs:
            tmp_mlx = Path(td) / key
            convert_to_tmp_mlx(mid, rev, tmp_mlx)
            asr_cfg = cfg_base.model_copy(
                update={
                    "model_id": mid,
                    "model_revision": rev,
                    "runtime": "mlx",
                    "auto_backend": "mlx",
                    "mlx_runtime_python": str(ROOT / ".venv-asr-mlx/bin/python"),
                    "mlx_model_dir": str(tmp_mlx),
                }
            )
            adapter = PhoWhisperAsrAdapter(asr_cfg, CACHE)
            p_m, s_m = eval_adapter(adapter, manifest136, f"{key}_manifest136")
            p_v, s_v = eval_adapter(adapter, vivos563, f"{key}_vivos563")
            summaries.extend([s_m, s_v])
            vivos_preds_by_model[key] = p_v
            write_csv(out_dir / f"{key}_vivos563.csv", p_v)
            if getattr(adapter, "_mlx_pipeline", None) is not None:
                adapter._mlx_pipeline.close()
            shutil.rmtree(tmp_mlx, ignore_errors=True)
            log(f"[Wave3D] Cleaned temp MLX weights {tmp_mlx}")

    # wav2vec2 baseline (CPU CTC)
    w2v_snap = CACHE / "models--nguyenvulebinh--wav2vec2-base-vietnamese-250h/snapshots/69e9000591623e5a4fc2f502407860bcdc0de0b2"
    w2v = make_wav2vec2_adapter(w2v_snap)
    p_w_m, s_w_m = eval_adapter(w2v, manifest136, "wav2vec2_vi_cpu_manifest136")
    p_w_v, s_w_v = eval_adapter(w2v, vivos563, "wav2vec2_vi_cpu_vivos563")
    summaries.extend([s_w_m, s_w_v])
    vivos_preds_by_model["wav2vec2_vi_cpu"] = p_w_v

    # Paired bootstrap vs Wave 2 PhoWhisper-medium MLX on vivos563
    paired = {}
    med_csv = OUT / "wave2/asr_mlx/med_mlx_vivos563.csv"
    if med_csv.is_file():
        with med_csv.open(encoding="utf-8") as f:
            med_rows = list(csv.DictReader(f))
        med_wers = [float(r["wer"]) for r in med_rows]
        for key, p_rows in vivos_preds_by_model.items():
            paired[f"{key}_vs_phowhisper_medium_mlx_vivos563"] = paired_bootstrap_ci(
                med_wers, [float(r["wer"]) for r in p_rows]
            )

    write_csv(out_dir / "summary.csv", summaries)
    write_json(
        out_dir / "results.json",
        {
            "benchmark": "wave3_asr_large_and_baselines",
            "elapsed_sec": round(time.perf_counter() - t0, 2),
            "peak_rss_mb": round(rss_mb(), 2),
            "summaries": summaries,
            "paired_bootstrap_vs_medium_mlx": paired,
        },
    )
    log(f"[Wave3D] Done in {time.perf_counter() - t0:.2f}s")


if __name__ == "__main__":
    main()

