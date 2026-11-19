"""Wave 2-2: Multi-source Fusion (F0-F5 vs AUDIO_DELAY_AND_SUM + afftdn) and Adaptive Routing on 24 multi-mic meetings."""

from __future__ import annotations

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
    log,
    paired_bootstrap_ci,
    read_json,
    rss_mb,
    setup_root_src,
    write_csv,
    write_json,
)


def main() -> None:
    setup_root_src()
    import jiwer
    import soundfile as sf
    from meeting_pipeline.adapters.phowhisper_asr import PhoWhisperAsrAdapter
    from meeting_pipeline.asr.cache import AsrCache
    from meeting_pipeline.asr.segment_asr import transcribe_turn_adaptive
    from meeting_pipeline.audio.synchronization import synchronize_multi_source_audio
    from meeting_pipeline.config import load_config
    from meeting_pipeline.data.vivos import normalize_vietnamese_text
    from meeting_pipeline.fusion.baselines import (
        fuse_f0_fixed,
        fuse_f1_best_segment,
        fuse_f2_oracle_best,
        fuse_f3_rover,
        fuse_f4_asr_weighted,
        fuse_f5_rule_weighted,
        fuse_f5_rule_weighted_corrected,
    )
    from meeting_pipeline.fusion.confusion_network import build_confusion_network

    t0 = time.perf_counter()
    cfg = load_config(ROOT / "configs/default.yaml")
    base_asr_cfg = cfg.asr.model_copy(
        update={
            "runtime": "mlx",
            "auto_backend": "mlx",
            "mlx_runtime_python": str(ROOT / ".venv-asr-mlx/bin/python"),
        }
    )
    adapter = PhoWhisperAsrAdapter(base_asr_cfg, CACHE)

    # All 24 multi-mic meetings (12 x 2-mic + 12 x 4-mic across val & test) from 20261104/simulation/manifest.json
    meetings = [
        m
        for m in read_json(CB_DATA / "simulation/manifest.json")
        if m["device_count"] >= 2 and m["split"] in {"validation", "test"}
    ]
    log(f"[Fusion] Evaluating {len(meetings)} multi-mic meetings ({sum(len(m['turns']) for m in meetings)} ref turns)...")

    with tempfile.TemporaryDirectory() as tmpdir:
        cache = AsrCache(Path(tmpdir) / "asr_cache", enabled=True)

        # Modes to run live via transcribe_turn_adaptive:
        # 1. transcript_all_source -> yields all source hypotheses -> exact F0, F1, F2, F3, F4, F5, F5_CORRECTED
        # 2. transcript_adaptive_max2 -> adaptive routing max_verification_sources=2
        # 3. transcript_adaptive_max3 -> adaptive routing max_verification_sources=3 (uncommitted default)
        # 4. audio_delay_sum_none -> fusion_mode="audio", audio_denoise="none"
        # 5. audio_delay_sum_afftdn -> fusion_mode="audio", audio_denoise="afftdn" (uncommitted default)
        cfg_all = base_asr_cfg.model_copy(update={"routing_mode": "all_source", "fusion_mode": "transcript"})
        cfg_adp2 = base_asr_cfg.model_copy(update={"routing_mode": "adaptive", "fusion_mode": "transcript", "max_verification_sources": 2})
        cfg_adp3 = base_asr_cfg.model_copy(update={"routing_mode": "adaptive", "fusion_mode": "transcript", "max_verification_sources": 3})
        cfg_aud_none = base_asr_cfg.model_copy(update={"fusion_mode": "audio", "audio_denoise": "none"})
        cfg_aud_aff = base_asr_cfg.model_copy(update={"fusion_mode": "audio", "audio_denoise": "afftdn"})

        per_turn = []
        mode_timings = {
            "transcript_all_source": 0.0,
            "transcript_adaptive_max2": 0.0,
            "transcript_adaptive_max3": 0.0,
            "audio_delay_sum_none": 0.0,
            "audio_delay_sum_afftdn": 0.0,
        }
        mode_asr_calls = {k: 0 for k in mode_timings}

        for m in meetings:
            sigs = {s["id"]: sf.read(s["path"], dtype="float32")[0] for s in m["sources"]}
            aligned, sync_meta, _ = synchronize_multi_source_audio(
                sigs, 16000, reference_source_id="source-1", allow_drift=True
            )
            turns = m["turns"]
            for idx, rt in enumerate(turns):
                prev_b = turns[idx - 1]["end_sec"] if idx > 0 else None
                next_b = turns[idx + 1]["start_sec"] if idx + 1 < len(turns) else None
                tid = f"{m['id']}_t{idx}"
                ref_norm = normalize_vietnamese_text(rt["reference"])

                # Run all_source first (warms cache)
                ts = time.perf_counter()
                hyp_all, meta_all = transcribe_turn_adaptive(
                    m["id"], tid, rt["start_sec"], rt["end_sec"], aligned, sync_meta, adapter, cfg_all, 16000, prev_b, next_b, cache=cache
                )
                mode_timings["transcript_all_source"] += time.perf_counter() - ts
                mode_asr_calls["transcript_all_source"] += meta_all["adapter_calls"]

                # Adaptive max=2 and max=3
                ts = time.perf_counter()
                hyp_adp2, meta_adp2 = transcribe_turn_adaptive(
                    m["id"], tid, rt["start_sec"], rt["end_sec"], aligned, sync_meta, adapter, cfg_adp2, 16000, prev_b, next_b, cache=cache
                )
                mode_timings["transcript_adaptive_max2"] += time.perf_counter() - ts
                mode_asr_calls["transcript_adaptive_max2"] += meta_adp2["adapter_calls"]

                ts = time.perf_counter()
                hyp_adp3, meta_adp3 = transcribe_turn_adaptive(
                    m["id"], tid, rt["start_sec"], rt["end_sec"], aligned, sync_meta, adapter, cfg_adp3, 16000, prev_b, next_b, cache=cache
                )
                mode_timings["transcript_adaptive_max3"] += time.perf_counter() - ts
                mode_asr_calls["transcript_adaptive_max3"] += meta_adp3["adapter_calls"]

                # Audio Delay-and-Sum (none & afftdn)
                ts = time.perf_counter()
                hyp_aud0, meta_aud0 = transcribe_turn_adaptive(
                    m["id"], tid, rt["start_sec"], rt["end_sec"], aligned, sync_meta, adapter, cfg_aud_none, 16000, prev_b, next_b, cache=cache
                )
                mode_timings["audio_delay_sum_none"] += time.perf_counter() - ts
                mode_asr_calls["audio_delay_sum_none"] += meta_aud0["adapter_calls"]

                ts = time.perf_counter()
                hyp_aud1, meta_aud1 = transcribe_turn_adaptive(
                    m["id"], tid, rt["start_sec"], rt["end_sec"], aligned, sync_meta, adapter, cfg_aud_aff, 16000, prev_b, next_b, cache=cache
                )
                mode_timings["audio_delay_sum_afftdn"] += time.perf_counter() - ts
                mode_asr_calls["audio_delay_sum_afftdn"] += meta_aud1["adapter_calls"]

                # Score transcript baselines on all_source hypotheses
                bins_all = build_confusion_network(hyp_all)
                t_f0, _ = fuse_f0_fixed(hyp_all, "source-1")
                t_f1, _ = fuse_f1_best_segment(hyp_all)
                t_f2, _ = fuse_f2_oracle_best(hyp_all, rt["reference"])
                t_f3, _ = fuse_f3_rover(bins_all)
                t_f4, _ = fuse_f4_asr_weighted(bins_all)
                t_f5, _ = fuse_f5_rule_weighted(bins_all)
                t_f5c, _ = fuse_f5_rule_weighted_corrected(bins_all, hyp_all)

                bins_adp2 = build_confusion_network(hyp_adp2)
                t_adp2, _ = fuse_f5_rule_weighted_corrected(bins_adp2, hyp_adp2)
                bins_adp3 = build_confusion_network(hyp_adp3)
                t_adp3, _ = fuse_f5_rule_weighted_corrected(bins_adp3, hyp_adp3)

                t_aud0 = next((h.text for h in hyp_aud0.values() if h.asr_status == "transcribed"), "")
                t_aud1 = next((h.text for h in hyp_aud1.values() if h.asr_status == "transcribed"), "")
                aud0_fallback = (meta_aud0.get("audio_fusion") or {}).get("fallback_reason")
                aud1_fallback = (meta_aud1.get("audio_fusion") or {}).get("fallback_reason")

                methods_text = {
                    "F0_FIXED": t_f0,
                    "F1_BEST_SEGMENT": t_f1,
                    "F2_ORACLE_BEST": t_f2,
                    "F3_ROVER": t_f3,
                    "F4_ASR_WEIGHTED": t_f4,
                    "F5_RULE_WEIGHTED": t_f5,
                    "F5_RULE_WEIGHTED_CORRECTED_ALL": t_f5c,
                    "F5_CORRECTED_ADAPTIVE_MAX2": t_adp2,
                    "F5_CORRECTED_ADAPTIVE_MAX3": t_adp3,
                    "AUDIO_DELAY_SUM_RAW": t_aud0,
                    "AUDIO_DELAY_SUM_AFFTDN": t_aud1,
                }
                for mname, hyp_raw in methods_text.items():
                    hn = normalize_vietnamese_text(hyp_raw)
                    per_turn.append(
                        {
                            "meeting": m["id"],
                            "turn_id": tid,
                            "condition": m["condition"],
                            "device_count": m["device_count"],
                            "method": mname,
                            "ref": ref_norm,
                            "hyp": hn,
                            "wer": float(jiwer.wer([ref_norm], [hn])),
                            "cer": float(jiwer.cer([ref_norm], [hn])),
                            "scheduled": (
                                len(meta_adp2["scheduled_sources"]) if mname == "F5_CORRECTED_ADAPTIVE_MAX2"
                                else len(meta_adp3["scheduled_sources"]) if mname == "F5_CORRECTED_ADAPTIVE_MAX3"
                                else len(meta_aud0["scheduled_sources"]) if mname.startswith("AUDIO_")
                                else len(meta_all["scheduled_sources"])
                            ),
                            "fallback": aud0_fallback if mname == "AUDIO_DELAY_SUM_RAW" else (aud1_fallback if mname == "AUDIO_DELAY_SUM_AFFTDN" else None),
                        }
                    )

    methods_order = [
        "F0_FIXED",
        "F1_BEST_SEGMENT",
        "F2_ORACLE_BEST",
        "F3_ROVER",
        "F4_ASR_WEIGHTED",
        "F5_RULE_WEIGHTED",
        "F5_RULE_WEIGHTED_CORRECTED_ALL",
        "F5_CORRECTED_ADAPTIVE_MAX2",
        "F5_CORRECTED_ADAPTIVE_MAX3",
        "AUDIO_DELAY_SUM_RAW",
        "AUDIO_DELAY_SUM_AFFTDN",
    ]
    summary_rows = []
    for mname in methods_order:
        for grp_name, pred_fn in [
            ("all_24", lambda r: True),
            ("2mic_12", lambda r: r["device_count"] == 2),
            ("4mic_12", lambda r: r["device_count"] == 4),
            ("stress", lambda r: r["condition"] == "stress"),
        ]:
            sel = [r for r in per_turn if r["method"] == mname and pred_fn(r)]
            refs = [r["ref"] for r in sel]
            hyps = [r["hyp"] for r in sel]
            summary_rows.append(
                {
                    "method": mname,
                    "subset": grp_name,
                    "turns": len(sel),
                    "corpus_wer": round(float(jiwer.wer(refs, hyps)), 4),
                    "corpus_cer": round(float(jiwer.cer(refs, hyps)), 4),
                    "avg_scheduled_sources": round(sum(r["scheduled"] for r in sel) / len(sel), 3),
                    "audio_fallback_count": sum(bool(r["fallback"]) for r in sel),
                }
            )

    # Paired bootstrap CIs on all 96 turns
    def turn_wers(mname):
        return [r["wer"] for r in per_turn if r["method"] == mname]

    paired = {
        "F5_corr_vs_F0_wer": paired_bootstrap_ci(turn_wers("F0_FIXED"), turn_wers("F5_RULE_WEIGHTED_CORRECTED_ALL")),
        "Audio_afftdn_vs_F0_wer": paired_bootstrap_ci(turn_wers("F0_FIXED"), turn_wers("AUDIO_DELAY_SUM_AFFTDN")),
        "Audio_afftdn_vs_Audio_raw_wer": paired_bootstrap_ci(turn_wers("AUDIO_DELAY_SUM_RAW"), turn_wers("AUDIO_DELAY_SUM_AFFTDN")),
        "Audio_afftdn_vs_F5_corr_wer": paired_bootstrap_ci(turn_wers("F5_RULE_WEIGHTED_CORRECTED_ALL"), turn_wers("AUDIO_DELAY_SUM_AFFTDN")),
    }

    out_dir = OUT / "wave2/fusion"
    write_csv(out_dir / "summary.csv", summary_rows)
    write_json(
        out_dir / "results.json",
        {
            "benchmark": "wave2_multisource_fusion_and_routing",
            "elapsed_sec": round(time.perf_counter() - t0, 2),
            "peak_rss_mb": round(rss_mb(), 2),
            "meetings": len(meetings),
            "mode_timings_sec": {k: round(v, 2) for k, v in mode_timings.items()},
            "mode_asr_calls": mode_asr_calls,
            "summary": summary_rows,
            "paired_bootstrap": paired,
        },
    )
    log(f"[Fusion] Done in {time.perf_counter() - t0:.2f}s")


if __name__ == "__main__":
    main()

