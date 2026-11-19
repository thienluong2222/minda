"""Wave 2-1: ASR MLX benchmark (PhoWhisper-medium vs PhoWhisper-small MLX, word confidence, CPU fallback guard <0.8s)."""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    CB_DATA,
    CACHE,
    OUT,
    ROOT,
    SEED,
    log,
    paired_bootstrap_ci,
    read_json,
    rss_mb,
    setup_root_src,
    write_csv,
    write_json,
)


def make_adapter(model_id: str, revision: str, runtime: str, auto_backend: str = "mlx"):
    from meeting_pipeline.adapters.phowhisper_asr import PhoWhisperAsrAdapter
    from meeting_pipeline.config import load_config

    cfg = load_config(ROOT / "configs/default.yaml")
    asr_cfg = cfg.asr.model_copy(
        update={
            "model_id": model_id,
            "model_revision": revision,
            "runtime": runtime,
            "auto_backend": auto_backend,
            "mlx_runtime_python": str(ROOT / ".venv-asr-mlx/bin/python"),
        }
    )
    return PhoWhisperAsrAdapter(asr_cfg, CACHE), asr_cfg


def build_short_boundary_set() -> list[dict]:
    """Build 80 short-duration boundary clips (40 < 0.8s, 40 in 0.8..1.6s) from VIVOS test."""
    import numpy as np
    import soundfile as sf

    out_dir = OUT / "cache/short_clips_80"
    manifest_p = out_dir / "manifest.json"
    if manifest_p.is_file():
        return read_json(manifest_p)
    out_dir.mkdir(parents=True, exist_ok=True)
    vivos = [json.loads(l) for l in (ROOT / "data/manifests/vivos.jsonl").read_text().splitlines() if l.strip()]
    pool = sorted(
        [r for r in vivos if r["split"] == "test" and not r["is_enrollment"]],
        key=lambda x: x["duration_sec"],
    )
    # 40 very short slices (0.45s - 0.72s) from beginning of utterances (energy onset) + 40 short whole utterances (0.85s - 1.7s)
    rng = np.random.default_rng(SEED + 80)
    short_rows = []
    for i in range(40):
        row = pool[(i * 7) % len(pool)]
        wav, sr = sf.read(ROOT / row["audio_path"], dtype="float32")
        dur = float(rng.uniform(0.45, 0.72))
        n = min(len(wav), int(round(dur * sr)))
        clip = wav[:n]
        p = out_dir / f"sub08_{i:02d}.wav"
        sf.write(p, clip, sr, subtype="PCM_16")
        short_rows.append({"id": f"sub08_{i:02d}", "bucket": "lt_0.8s", "duration_sec": len(clip) / sr, "path": str(p), "reference": row["text_normalized"]})

    # For 0.8..1.6s bucket, pick shortest VIVOS utterances around 1.0..1.8s
    mid_pool = [r for r in pool if 0.85 <= r["duration_sec"] <= 2.1]
    for i in range(40):
        row = mid_pool[i % len(mid_pool)]
        p = ROOT / row["audio_path"]
        short_rows.append({"id": f"ge08_{i:02d}", "bucket": "0.8_to_2.1s", "duration_sec": row["duration_sec"], "path": str(p), "reference": row["text_normalized"]})

    write_json(manifest_p, short_rows)
    return short_rows


def run_eval_set(adapter, rows: list[dict], label: str) -> tuple[list[dict], dict]:
    import jiwer
    import soundfile as sf
    from meeting_pipeline.data.vivos import normalize_vietnamese_text

    preds = []
    t0 = time.perf_counter()
    audio_sec_total = 0.0
    confs = []
    cpu_fallbacks = 0
    empty_or_fail = 0

    for idx, r in enumerate(rows):
        w, sr = sf.read(r["path"], dtype="float32")
        if w.ndim > 1:
            w = w[:, 0]
        audio_sec_total += len(w) / sr
        s0 = time.perf_counter()
        res = adapter.transcribe(w, sr)
        dt = time.perf_counter() - s0

        hyp_norm = normalize_vietnamese_text(res.text)
        ref_norm = normalize_vietnamese_text(r["reference"])
        w_wer = float(jiwer.wer([ref_norm], [hyp_norm])) if ref_norm else (0.0 if not hyp_norm else 1.0)
        w_cer = float(jiwer.cer([ref_norm], [hyp_norm])) if ref_norm else (0.0 if not hyp_norm else 1.0)
        word_confs = [wd.confidence for wd in res.words if wd.confidence is not None]
        mean_c = float(sum(word_confs) / len(word_confs)) if word_confs else None
        if mean_c is not None:
            confs.append(mean_c)
        if any("cpu_fallback" in str(c) or "fallback" in str(w_) for w_ in res.warnings for c in [w_]):
            cpu_fallbacks += 1
        if res.status != "transcribed":
            empty_or_fail += 1

        preds.append(
            {
                "id": r["id"],
                "split": r.get("split", r.get("bucket", "all")),
                "condition": r.get("condition", r.get("bucket", "clean")),
                "duration_sec": round(len(w) / sr, 3),
                "ref_norm": ref_norm,
                "hyp_norm": hyp_norm,
                "wer": w_wer,
                "cer": w_cer,
                "status": res.status,
                "warnings": res.warnings,
                "mean_word_conf": mean_c,
                "seconds": round(dt, 4),
            }
        )
        if (idx + 1) % 50 == 0:
            log(f"[ASR {label}] {idx + 1}/{len(rows)} ({time.perf_counter() - t0:.1f}s)")

    wall = time.perf_counter() - t0
    refs = [p["ref_norm"] for p in preds if p["ref_norm"]]
    hyps = [p["hyp_norm"] for p in preds if p["ref_norm"]]
    summary = {
        "label": label,
        "samples": len(preds),
        "audio_sec": round(audio_sec_total, 2),
        "wall_sec": round(wall, 2),
        "rtf": round(wall / max(audio_sec_total, 1e-6), 4),
        "corpus_wer": round(float(jiwer.wer(refs, hyps)), 4) if refs else None,
        "corpus_cer": round(float(jiwer.cer(refs, hyps)), 4) if refs else None,
        "non_transcribed": empty_or_fail,
        "mean_word_confidence": round(float(sum(confs) / len(confs)), 4) if confs else None,
        "confidence_coverage": round(len(confs) / max(len(preds), 1), 4),
        "warnings_count": sum(bool(p["warnings"]) for p in preds),
    }
    return preds, summary


def main() -> None:
    setup_root_src()
    import jiwer

    t_start = time.perf_counter()
    # Dataset 1: 136 test samples from 20261104/asr/manifest.json (76 degraded/clean test + 60 synthetic_test)
    asr_manifest = read_json(CB_DATA / "asr/manifest.json")
    manifest_test = [r for r in asr_manifest if r["split"] in {"test", "synthetic_test"}]
    for r in manifest_test:
        r["path"] = r["audio_path"]
    syn_test = [r for r in manifest_test if r["split"] == "synthetic_test"]

    # Dataset 2: Full 563 non-enrollment test utterances from VIVOS test
    vivos = [json.loads(l) for l in (ROOT / "data/manifests/vivos.jsonl").read_text().splitlines() if l.strip()]
    vivos_test = [
        {"id": r["utterance_id"], "split": "vivos_test_563", "condition": "clean", "path": str(ROOT / r["audio_path"]), "reference": r["text_normalized"]}
        for r in vivos
        if r["split"] == "test" and not r.get("is_enrollment")
    ]

    # Dataset 3: 80 short boundary clips (<0.8s vs 0.8..2.1s)
    short_rows = build_short_boundary_set()

    out_dir = OUT / "wave2/asr_mlx"
    out_dir.mkdir(parents=True, exist_ok=True)
    summaries = []
    paired_stats = {}

    # 1. PhoWhisper-medium MLX on synthetic_test (60) + test (76) + full VIVOS test (563) + short (80)
    ad_med_mlx, _ = make_adapter("vinai/PhoWhisper-medium", "55a7e3eb6c906de891f8f06a107754427dd3be79", "mlx", "mlx")
    p_med_m, s_med_m = run_eval_set(ad_med_mlx, manifest_test, "phowhisper_medium_mlx_manifest136")
    p_med_v, s_med_v = run_eval_set(ad_med_mlx, vivos_test, "phowhisper_medium_mlx_vivos563")
    p_med_sh, s_med_sh = run_eval_set(ad_med_mlx, short_rows, "phowhisper_medium_mlx_short80")
    summaries.extend([s_med_m, s_med_v, s_med_sh])
    write_csv(out_dir / "med_mlx_vivos563.csv", p_med_v)

    # 2. PhoWhisper-small MLX on same sets
    ad_sm_mlx, _ = make_adapter("vinai/PhoWhisper-small", "a86b604c346caf7148c37512eafe783a16420adb", "mlx", "mlx")
    p_sm_m, s_sm_m = run_eval_set(ad_sm_mlx, manifest_test, "phowhisper_small_mlx_manifest136")
    p_sm_v, s_sm_v = run_eval_set(ad_sm_mlx, vivos_test, "phowhisper_small_mlx_vivos563")
    p_sm_sh, s_sm_sh = run_eval_set(ad_sm_mlx, short_rows, "phowhisper_small_mlx_short80")
    summaries.extend([s_sm_m, s_sm_v, s_sm_sh])
    write_csv(out_dir / "sm_mlx_vivos563.csv", p_sm_v)

    # 3. Direct parity check vs MPS/CPU fallback on synthetic_test (60 clips) and short80
    ad_med_mps, _ = make_adapter("vinai/PhoWhisper-medium", "55a7e3eb6c906de891f8f06a107754427dd3be79", "mps", "mps")
    p_med_mps_syn, s_med_mps_syn = run_eval_set(ad_med_mps, syn_test, "phowhisper_medium_mps_syn60")
    p_med_mps_sh, s_med_mps_sh = run_eval_set(ad_med_mps, short_rows, "phowhisper_medium_mps_short80")
    ad_sm_mps, _ = make_adapter("vinai/PhoWhisper-small", "a86b604c346caf7148c37512eafe783a16420adb", "mps", "mps")
    p_sm_mps_syn, s_sm_mps_syn = run_eval_set(ad_sm_mps, syn_test, "phowhisper_small_mps_syn60")
    summaries.extend([s_med_mps_syn, s_med_mps_sh, s_sm_mps_syn])

    # Breakdown manifest136 by split/condition
    breakdown = []
    for lbl, preds in [("medium_mlx", p_med_m), ("small_mlx", p_sm_m)]:
        for grp in [("test", "clean"), ("test", "moderate"), ("test", "stress"), ("synthetic_test", "clean_control"), ("synthetic_test", "easy"), ("synthetic_test", "moderate"), ("synthetic_test", "stress")]:
            sel = [p for p in preds if p["split"] == grp[0] and p["condition"] == grp[1]]
            if not sel:
                continue
            refs = [p["ref_norm"] for p in sel]
            hyps = [p["hyp_norm"] for p in sel]
            breakdown.append(
                {
                    "model": lbl,
                    "split": grp[0],
                    "condition": grp[1],
                    "samples": len(sel),
                    "wer": round(float(jiwer.wer(refs, hyps)), 4),
                    "cer": round(float(jiwer.cer(refs, hyps)), 4),
                }
            )
    # Short80 breakdown (<0.8s vs >=0.8s)
    for lbl, preds in [("medium_mlx", p_med_sh), ("small_mlx", p_sm_sh), ("medium_mps", p_med_mps_sh)]:
        for bkt in ("lt_0.8s", "0.8_to_2.1s"):
            sel = [p for p in preds if p["condition"] == bkt]
            refs = [p["ref_norm"] for p in sel]
            hyps = [p["hyp_norm"] for p in sel]
            breakdown.append(
                {
                    "model": lbl,
                    "split": "short_boundary_80",
                    "condition": bkt,
                    "samples": len(sel),
                    "wer": round(float(jiwer.wer(refs, hyps)), 4),
                    "cer": round(float(jiwer.cer(refs, hyps)), 4),
                    "non_transcribed": sum(p["status"] != "transcribed" for p in sel),
                    "avg_sec": round(sum(p["seconds"] for p in sel) / len(sel), 3),
                }
            )

    # Paired bootstrap CIs (medium MLX vs small MLX on 563 VIVOS; medium MLX vs MPS on 60 syn_test)
    paired_stats["medium_vs_small_mlx_vivos563_wer"] = paired_bootstrap_ci(
        [p["wer"] for p in p_sm_v], [p["wer"] for p in p_med_v]
    )
    med_mlx_syn60 = [p for p in p_med_m if p["split"] == "synthetic_test"]
    paired_stats["medium_mlx_vs_mps_syn60_wer"] = paired_bootstrap_ci(
        [p["wer"] for p in p_med_mps_syn], [p["wer"] for p in med_mlx_syn60]
    )

    write_csv(out_dir / "summary.csv", summaries)
    write_csv(out_dir / "breakdown.csv", breakdown)
    write_json(
        out_dir / "results.json",
        {
            "benchmark": "wave2_asr_mlx",
            "elapsed_sec": round(time.perf_counter() - t_start, 2),
            "peak_rss_mb": round(rss_mb(), 2),
            "summaries": summaries,
            "breakdown": breakdown,
            "paired_bootstrap": paired_stats,
        },
    )
    log(f"[ASR MLX] Done in {time.perf_counter() - t_start:.2f}s")


if __name__ == "__main__":
    main()
