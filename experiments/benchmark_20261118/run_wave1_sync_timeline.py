"""Wave 1-5: Multi-source audio synchronization & TimelineAudioPipeline pause/resume benchmark."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CB_DATA, OUT, ROOT, SEED, log, read_json, rss_mb, setup_root_src, write_csv, write_json


def make_synthetic_sync_datasets(base_dir: Path) -> tuple[list[dict], list[dict]]:
    """Build 12 long continuous drift/offset cases + 12 pause/resume split-clock cases from VIVOS test speakers."""
    import numpy as np
    import soundfile as sf
    from scipy.signal import fftconvolve

    from meeting_pipeline.simulation.device import apply_clock_drift, apply_start_offset
    from meeting_pipeline.simulation.room import compute_room_rirs

    base_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = base_dir / "manifest.json"
    if manifest_file.is_file():
        data = read_json(manifest_file)
        return data["continuous"], data["pause_resume"]

    vivos = [json.loads(l) for l in (ROOT / "data/manifests/vivos.jsonl").read_text().splitlines() if l.strip()]
    test_pool = [r for r in vivos if r["split"] == "test" and not r["is_enrollment"] and 2.5 <= r["duration_sec"] <= 6.0]
    by_spk = {}
    for r in test_pool:
        by_spk.setdefault(r["speaker_id"], []).append(r)

    rng = np.random.default_rng(SEED + 505)
    sr = 16000
    continuous_cases = []
    pause_cases = []

    def build_base_meeting(case_seed: int, duration_target: float = 90.0):
        r_local = np.random.default_rng(case_seed)
        spks = sorted(r_local.choice(sorted(by_spk), 3, replace=False).tolist())
        clips = []
        clock = 1.0
        idx = 0
        while clock < duration_target - 5.0:
            sp = spks[idx % len(spks)]
            row = by_spk[sp][int(r_local.integers(len(by_spk[sp])))]
            wave, rate = sf.read(ROOT / row["audio_path"], dtype="float32")
            assert rate == sr
            clips.append((sp, clock, wave))
            clock += len(wave) / sr + float(r_local.uniform(0.35, 1.1))
            idx += 1
        total_samples = int((clock + 2.0) * sr)
        stems = {sp: np.zeros(total_samples, dtype=np.float32) for sp in spks}
        for sp, t_start, w in clips:
            a = int(round(t_start * sr))
            stems[sp][a : a + len(w)] += w
        pos = {sp: [1.5 + i * 1.4, 1.4 + (i % 2) * 1.1, 1.2] for i, sp in enumerate(spks)}
        devs = {"source-1": [1.5, 2.2, 0.85], "source-2": [2.8, 2.3, 0.85], "source-3": [3.9, 1.9, 0.85]}
        rirs = compute_room_rirs([6.0, 4.0, 2.8], rt60=0.28, speaker_positions=pos, device_positions=devs, sample_rate=sr)
        rendered = {}
        for d_idx, dev in enumerate(devs):
            clean = sum(fftconvolve(stems[sp], rirs[sp][dev]).astype(np.float32)[:total_samples] for sp in spks)
            noise = r_local.normal(size=total_samples).astype(np.float32)
            snr = 20.0 - 3.0 * d_idx
            noise *= np.sqrt(np.mean(clean**2) / (10 ** (snr / 10) * np.mean(noise**2) + 1e-12))
            sig = clean + noise
            peak = float(np.max(np.abs(sig)))
            if peak > 0.95:
                sig *= 0.95 / peak
            rendered[dev] = sig.astype(np.float32)
        return rendered

    # 12 long continuous meetings with large offsets & clock drift
    offset_grid = [2.5, -3.2, 5.4, -7.8, 10.5, 14.2, -12.0, 18.0, 4.0, -6.5, 8.7, -15.5]
    drift_grid = [45.0, -60.0, 85.0, -95.0, 110.0, -40.0, 75.0, -120.0, 55.0, -80.0, 100.0, -50.0]
    for i in range(12):
        cid = f"sync_cont_{i:02d}"
        cdir = base_dir / cid
        cdir.mkdir(parents=True, exist_ok=True)
        sigs = build_base_meeting(SEED + 100 + i, duration_target=90.0)
        # Keep source-1 canonical at offset=0, drift=0; shift source-2 and source-3
        off2 = offset_grid[i]
        dr2 = drift_grid[i]
        off3 = -0.5 * off2
        dr3 = -0.7 * dr2
        out_sigs = {
            "source-1": sigs["source-1"],
            "source-2": apply_start_offset(apply_clock_drift(sigs["source-2"], dr2), off2, sr),
            "source-3": apply_start_offset(apply_clock_drift(sigs["source-3"], dr3), off3, sr),
        }
        paths = {}
        for sid, s in out_sigs.items():
            p = cdir / f"{sid}.wav"
            sf.write(p, s, sr, subtype="PCM_16")
            paths[sid] = str(p)
        continuous_cases.append(
            {
                "id": cid,
                "paths": paths,
                "reference_source": "source-1",
                "truth": {
                    "source-2": {"offset_sec": off2, "drift_ppm": dr2},
                    "source-3": {"offset_sec": off3, "drift_ppm": dr3},
                },
            }
        )

    # 12 pause/resume cases (paused device drops 14-24s in middle and resumes without padding)
    for i in range(12):
        cid = f"sync_pause_{i:02d}"
        cdir = base_dir / cid
        cdir.mkdir(parents=True, exist_ok=True)
        sigs = build_base_meeting(SEED + 200 + i, duration_target=90.0)
        ref = sigs["source-1"]
        src2_full = sigs["source-2"]
        split_at = float(28.0 + (i % 4) * 4.0)
        gap_sec = float(14.0 + (i % 5) * 2.5)
        start_trim = float(2.0 + (i % 3) * 1.5)
        s0 = int(round(start_trim * sr))
        s1 = int(round(split_at * sr))
        s2 = int(round((split_at + gap_sec) * sr))
        part1 = src2_full[s0:s1]
        part2 = src2_full[s2:]
        concat_paused = np.concatenate([part1, part2]).astype(np.float32)

        p_ref = cdir / "continuous.wav"
        p_paused = cdir / "paused.wav"
        p_clip1 = cdir / "clip1.wav"
        p_clip2 = cdir / "clip2.wav"
        sf.write(p_ref, ref, sr, subtype="PCM_16")
        sf.write(p_paused, concat_paused, sr, subtype="PCM_16")
        sf.write(p_clip1, part1, sr, subtype="PCM_16")
        sf.write(p_clip2, part2, sr, subtype="PCM_16")
        pause_cases.append(
            {
                "id": cid,
                "continuous_path": str(p_ref),
                "paused_path": str(p_paused),
                "clip1_path": str(p_clip1),
                "clip2_path": str(p_clip2),
                "true_span1_offset": start_trim,
                "true_span1_end_in_query": len(part1) / sr,
                "true_span2_offset": start_trim + gap_sec,
                "true_gap_sec": gap_sec,
            }
        )

    write_json(manifest_file, {"continuous": continuous_cases, "pause_resume": pause_cases})
    return continuous_cases, pause_cases


def main() -> None:
    setup_root_src()
    import numpy as np
    import soundfile as sf
    from meeting_pipeline.audio.fingerprints import fingerprint
    from meeting_pipeline.audio.synchronization import synchronize_multi_source_audio
    from meeting_pipeline.audio.timeline_alignment import resolve_clocks

    t0 = time.perf_counter()
    syn_dir = OUT / "wave1/sync_synthetic"
    cont_cases, pause_cases = make_synthetic_sync_datasets(syn_dir)

    # 1. Existing 24 multi-mic short meetings from 20261104/simulation/manifest.json
    sim_all = [
        m for m in read_json(CB_DATA / "simulation/manifest.json")
        if m["device_count"] >= 2 and m["split"] in {"validation", "test"}
    ]
    short_rows = []
    for m in sim_all:
        sigs = {s["id"]: sf.read(s["path"], dtype="float32")[0] for s in m["sources"]}
        truth_off = {s["id"]: float(s["offset_sec"]) for s in m["sources"]}
        for mode_name, allow_drift in [("offset_only", False), ("full_sync", True)]:
            ts = time.perf_counter()
            _, meta, ref_id = synchronize_multi_source_audio(
                sigs, 16000, reference_source_id="source-1", allow_drift=allow_drift
            )
            dt = time.perf_counter() - ts
            for sid, true_o in truth_off.items():
                if sid == ref_id:
                    continue
                # apply_start_offset(+X) delays signal -> sync returns offset_sec = -X
                pred_o = -float(meta[sid]["offset_sec"])
                short_rows.append(
                    {
                        "suite": "sim_short_24",
                        "meeting": m["id"],
                        "mode": mode_name,
                        "source_id": sid,
                        "offset_err_ms": abs(pred_o - true_o) * 1000.0,
                        "drift_err_ppm": abs(float(meta[sid]["drift_ppm"]) - 0.0),
                        "drift_status": meta[sid].get("drift_status"),
                        "seconds": dt,
                    }
                )

    # 2a. 12 continuous 90s meetings (large offsets +-2.5..18s + sub-threshold realistic drift +-40..120 ppm)
    # 2b. 6 continuous 120s meetings with multi-bin drift (+-450..1100 ppm -> >50ms total drift, above 10ms envelope bin)
    from meeting_pipeline.simulation.device import apply_clock_drift, apply_start_offset
    cont_rows = []
    for idx_c, c in enumerate(cont_cases):
        sigs = {sid: sf.read(p, dtype="float32")[0] for sid, p in c["paths"].items()}
        for sid, tr in c["truth"].items():
            cont_rows.append(
                {
                    "suite": "vivos_long_low_drift_12",
                    "meeting": c["id"],
                    "mode": "no_sync",
                    "source_id": sid,
                    "offset_err_ms": abs(0.0 - tr["offset_sec"]) * 1000.0,
                    "drift_err_ppm": abs(0.0 - tr["drift_ppm"]),
                    "drift_status": "none",
                    "seconds": 0.0,
                }
            )
        for mode_name, allow_drift in [("offset_only", False), ("full_sync", True)]:
            ts = time.perf_counter()
            _, meta, ref_id = synchronize_multi_source_audio(
                sigs, 16000, reference_source_id=c["reference_source"], allow_drift=allow_drift
            )
            dt = time.perf_counter() - ts
            for sid, tr in c["truth"].items():
                pred_o = -float(meta[sid]["offset_sec"])
                pred_dr = float(meta[sid]["drift_ppm"])
                cont_rows.append(
                    {
                        "suite": "vivos_long_low_drift_12",
                        "meeting": c["id"],
                        "mode": mode_name,
                        "source_id": sid,
                        "offset_err_ms": abs(pred_o - tr["offset_sec"]) * 1000.0,
                        "drift_err_ppm": min(abs(pred_dr - tr["drift_ppm"]), abs(-pred_dr - tr["drift_ppm"])),
                        "drift_status": meta[sid].get("drift_status"),
                        "seconds": dt,
                    }
                )

    high_drifts = [450.0, -600.0, 750.0, -900.0, 1050.0, -520.0]
    for i, hd in enumerate(high_drifts):
        c = cont_cases[i]
        ref_sig = sf.read(c["paths"]["source-1"], dtype="float32")[0]
        # Repeat slightly if < 110s? 90s * 1050ppm = 94.5ms (9+ envelope bins!)
        drifted = apply_start_offset(apply_clock_drift(ref_sig * 0.85, hd), 4.2, 16000)
        for mode_name, allow_drift in [("offset_only", False), ("full_sync", True)]:
            ts = time.perf_counter()
            _, meta, _ = synchronize_multi_source_audio(
                {"source-1": ref_sig, "source-h": drifted}, 16000, reference_source_id="source-1", allow_drift=allow_drift
            )
            dt = time.perf_counter() - ts
            pred_o = -float(meta["source-h"]["offset_sec"])
            pred_dr = float(meta["source-h"]["drift_ppm"])
            cont_rows.append(
                {
                    "suite": "vivos_high_drift_6",
                    "meeting": f"hd_{i:02d}",
                    "mode": mode_name,
                    "source_id": "source-h",
                    "offset_err_ms": abs(pred_o - 4.2) * 1000.0,
                    "drift_err_ppm": abs(pred_dr - hd),
                    "drift_status": meta["source-h"].get("drift_status"),
                    "seconds": dt,
                }
            )

    # 3. 12 Pause/Resume cases under BOTH (a) shared acoustics + noise and (b) multi-mic cross-room RIR
    pause_rows = []
    rng_p = np.random.default_rng(SEED + 777)
    for c in pause_cases:
        ref = sf.read(c["continuous_path"], dtype="float32")[0]
        paused_rir = sf.read(c["paused_path"], dtype="float32")[0]
        # Shared-acoustics paused (same room position + gain 0.75 + 22dB independent noise)
        sr = 16000
        s0 = int(round(c["true_span1_offset"] * sr))
        part1_len = int(round(c["true_span1_end_in_query"] * sr))
        s1 = s0 + part1_len
        s2 = int(round((c["true_span2_offset"] + c["true_span1_end_in_query"]) * sr))
        paused_shared_clean = np.concatenate([ref[s0:s1], ref[s2:]]) * 0.75
        noise = rng_p.normal(size=len(paused_shared_clean)).astype(np.float32)
        noise *= np.sqrt(np.mean(paused_shared_clean**2) / (10 ** (22.0 / 10) * np.mean(noise**2) + 1e-12))
        paused_shared = (paused_shared_clean + noise).astype(np.float32)

        for cond_name, q_wave in [("shared_acoustics_22db", paused_shared), ("cross_room_rir", paused_rir)]:
            ts1 = time.perf_counter()
            _, meta_cont, _ = synchronize_multi_source_audio(
                {"continuous": ref, "paused": q_wave}, 16000, reference_source_id="continuous", allow_drift=True
            )
            t_cont = time.perf_counter() - ts1
            naive_off = -float(meta_cont["paused"]["offset_sec"])
            naive_span2_err_ms = abs(naive_off - c["true_span2_offset"]) * 1000.0

            waves = {"continuous": ref, "paused": q_wave}
            layout = {
                "clips": [
                    {"id": "continuous", "asset_id": "continuous", "source_in_ms": 0, "source_out_ms": round(len(ref) / 16), "placement": {"kind": "sequential", "gap_before_ms": None}},
                    {"id": "paused", "asset_id": "paused", "source_in_ms": 0, "source_out_ms": round(len(q_wave) / 16), "placement": {"kind": "sequential", "gap_before_ms": None}},
                ],
                "tracks": [{"id": "continuous", "clip_ids": ["continuous"]}, {"id": "paused", "clip_ids": ["paused"]}],
                "intervals": [],
            }
            ts2 = time.perf_counter()
            report = resolve_clocks(
                layout,
                {k: len(v) / 16000.0 for k, v in waves.items()},
                {k: fingerprint(v, 16000) for k, v in waves.items()},
                waves.__getitem__,
                16000,
            )
            t_tl = time.perf_counter() - ts2
            spans = report.get("spans", {}).get("paused", [])
            acoustic_spans = [s for s in spans if s.get("origin") == "acoustic"]
            if len(acoustic_spans) >= 2:
                sp1_err = abs(float(acoustic_spans[0]["offset"]) - c["true_span1_offset"]) * 1000.0
                sp2_err = abs(float(acoustic_spans[1]["offset"]) - c["true_span2_offset"]) * 1000.0
            elif len(acoustic_spans) == 1:
                sp1_err = abs(float(acoustic_spans[0]["offset"]) - c["true_span1_offset"]) * 1000.0
                sp2_err = abs(float(acoustic_spans[0]["offset"]) - c["true_span2_offset"]) * 1000.0
            else:
                sp1_err = abs(0.0 - c["true_span1_offset"]) * 1000.0
                sp2_err = abs(0.0 - c["true_span2_offset"]) * 1000.0

            pause_rows.append(
                {
                    "condition": cond_name,
                    "case_id": c["id"],
                    "true_gap_sec": c["true_gap_sec"],
                    "naive_span1_err_ms": round(abs(naive_off - c["true_span1_offset"]) * 1000.0, 2),
                    "naive_span2_err_ms": round(naive_span2_err_ms, 2),
                    "timeline_spans_detected": len(acoustic_spans),
                    "total_spans": len(spans),
                    "timeline_complete": bool(report.get("timing_complete")),
                    "timeline_span1_err_ms": round(sp1_err, 2),
                    "timeline_span2_err_ms": round(sp2_err, 2),
                    "sync_sec": round(t_cont, 3),
                    "timeline_sec": round(t_tl, 3),
                }
            )

    # 4. Real 4-mic LibriWASN OV20 (session 4 & session 5, first 180s window relative to Soundcard)
    libri_root = ROOT / "data/external/libriwasn/LibriWASN/200/OV20"
    libri_rows = []
    for sess_dir in sorted(libri_root.iterdir()):
        if not sess_dir.is_dir():
            continue
        rec = sess_dir / "record"
        wavs = sorted(rec.glob("*.wav"))
        sigs = {}
        ref_id = None
        for w in wavs:
            # Read first 180s to avoid multi-channel huge memory; Soundcard has 4-8ch so average/take ch0
            info = sf.info(w)
            n_frames = min(info.frames, 180 * info.samplerate)
            audio, sr_w = sf.read(w, frames=n_frames, dtype="float32")
            if audio.ndim > 1:
                audio = audio[:, 0]
            if sr_w != 16000:
                import librosa
                audio = librosa.resample(audio, orig_sr=sr_w, target_sr=16000)
            key = w.stem.split("_")[0]
            sigs[key] = audio.astype(np.float32)
            if "Soundcard" in w.stem:
                ref_id = key
        ts = time.perf_counter()
        aligned, meta, ref_used = synchronize_multi_source_audio(
            sigs, 16000, reference_source_id=ref_id, allow_drift=True
        )
        dt = time.perf_counter() - ts
        # Check cross-correlation improvement before vs after sync against Soundcard
        ref_al = aligned[ref_used]
        ref_raw = sigs[ref_used]
        for k, m in meta.items():
            if k == ref_used:
                continue
            n_min = (min(len(ref_raw), len(sigs[k])) // 160) * 160
            env_raw = np.abs(ref_raw[:n_min]).reshape(-1, 160).mean(axis=1)
            env_k_raw = np.abs(sigs[k][:n_min]).reshape(-1, 160).mean(axis=1)
            corr_before = float(np.corrcoef(env_raw, env_k_raw)[0, 1])

            n_al = (min(len(ref_al), len(aligned[k])) // 160) * 160
            env_a = np.abs(ref_al[:n_al]).reshape(-1, 160).mean(axis=1)
            env_b = np.abs(aligned[k][:n_al]).reshape(-1, 160).mean(axis=1)
            corr_after = float(np.corrcoef(env_a, env_b)[0, 1])

            libri_rows.append(
                {
                    "session": sess_dir.name,
                    "device": k,
                    "reference": ref_used,
                    "offset_sec": round(float(m["offset_sec"]), 4),
                    "drift_ppm": round(float(m["drift_ppm"]), 2),
                    "residual_ms": round(float(m.get("residual_ms", 0.0)), 2),
                    "drift_status": m.get("drift_status"),
                    "env_corr_before": round(corr_before, 4),
                    "env_corr_after": round(corr_after, 4),
                    "seconds": round(dt, 2),
                }
            )

    def agg(rows: list[dict], suite: str) -> list[dict]:
        out = []
        for mode in sorted({r["mode"] for r in rows}):
            sel = [r for r in rows if r["mode"] == mode]
            out.append(
                {
                    "suite": suite,
                    "mode": mode,
                    "pairs": len(sel),
                    "offset_mae_ms": round(float(np.mean([r["offset_err_ms"] for r in sel])), 2),
                    "offset_median_ms": round(float(np.median([r["offset_err_ms"] for r in sel])), 2),
                    "offset_p95_ms": round(float(np.percentile([r["offset_err_ms"] for r in sel], 95)), 2),
                    "drift_mae_ppm": round(float(np.mean([r["drift_err_ppm"] for r in sel])), 2),
                    "unresolved_rate": round(float(np.mean([r["drift_status"] == "drift_unresolved" for r in sel])), 4),
                }
            )
        return out

    def agg_suite(rows: list[dict], suite: str) -> list[dict]:
        sub = [r for r in rows if r["suite"] == suite]
        return agg(sub, suite)

    pause_summary = {}
    for cond_name in ("shared_acoustics_22db", "cross_room_rir"):
        sub_p = [r for r in pause_rows if r["condition"] == cond_name]
        pause_summary[cond_name] = {
            "cases": len(sub_p),
            "multi_span_detection_rate": round(float(np.mean([r["timeline_spans_detected"] >= 2 for r in sub_p])), 4),
            "timing_complete_rate": round(float(np.mean([r["timeline_complete"] for r in sub_p])), 4),
            "naive_span2_mae_ms": round(float(np.mean([r["naive_span2_err_ms"] for r in sub_p])), 2),
            "timeline_span1_mae_ms": round(float(np.mean([r["timeline_span1_err_ms"] for r in sub_p])), 2),
            "timeline_span2_mae_ms": round(float(np.mean([r["timeline_span2_err_ms"] for r in sub_p])), 2),
        }

    summary = {
        "short_24_summary": agg(short_rows, "sim_short_24"),
        "long_low_drift_12_summary": agg_suite(cont_rows, "vivos_long_low_drift_12"),
        "high_drift_6_summary": agg_suite(cont_rows, "vivos_high_drift_6"),
        "pause_resume_summary": pause_summary,
        "libriwasn_4mic": libri_rows,
    }

    out_dir = OUT / "wave1/sync_timeline"
    write_csv(out_dir / "short_and_long.csv", [*short_rows, *cont_rows])
    write_csv(out_dir / "pause_resume.csv", pause_rows)
    write_csv(out_dir / "libriwasn.csv", libri_rows)
    write_json(
        out_dir / "results.json",
        {
            "benchmark": "wave1_sync_and_timeline",
            "elapsed_sec": round(time.perf_counter() - t0, 2),
            "peak_rss_mb": round(rss_mb(), 2),
            **summary,
        },
    )
    log(f"[Sync/Timeline] Done in {time.perf_counter() - t0:.2f}s")


if __name__ == "__main__":
    main()
