"""Wave 2-3: Core End-to-End Replay on ALL 30 test meetings comparing Baseline ECAPA vs WeSpeaker+MLX F5 vs WeSpeaker+MLX Audio+afftdn."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CB_DATA, CACHE, OUT, ROOT, log, read_json, rss_mb, setup_root_src, write_csv, write_json


class DiskCachedEncoder:
    def __init__(self, encoder: Any, cache_dir: Path, identity: str) -> None:
        self.encoder = encoder
        self.cache_dir = cache_dir
        self.identity = identity
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def encode(self, waveform):
        import numpy as np

        h = hashlib.sha256(self.identity.encode() + np.asarray(waveform, dtype=np.float32).tobytes()).hexdigest()
        p = self.cache_dir / f"{h}.npy"
        if p.is_file():
            return np.asarray(np.load(p), dtype=np.float32)
        vec = np.asarray(self.encoder.encode(waveform), dtype=np.float32)
        np.save(p, vec)
        return vec


def _pairwise_f1(labels: list[str], preds: list[str]) -> float:
    tp = fp = fn = 0
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            t = labels[i] == labels[j]
            g = preds[i] == preds[j]
            tp += int(t and g)
            fp += int(not t and g)
            fn += int(t and not g)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    return (2 * prec * rec / (prec + rec)) if prec + rec else 0.0


def _ref_label(start_sec: float, end_sec: float, ref_turns: list[dict]) -> str | None:
    best_ov = 0.0
    best_spk = None
    for rt in ref_turns:
        ov = max(0.0, min(end_sec, rt["end_sec"]) - max(start_sec, rt["start_sec"]))
        if ov > best_ov:
            best_ov = ov
            best_spk = rt["speaker"]
    return best_spk if best_ov >= 0.5 * max(end_sec - start_sec, 1e-6) else None


def main() -> None:
    setup_root_src()
    import jiwer
    import numpy as np
    import soundfile as sf
    from meeting_pipeline.adapters.phowhisper_asr import PhoWhisperAsrAdapter
    from meeting_pipeline.asr.cache import AsrCache
    from meeting_pipeline.asr.segment_asr import transcribe_turn_adaptive
    from meeting_pipeline.config import load_config
    from meeting_pipeline.data.vivos import normalize_vietnamese_text
    from meeting_pipeline.fusion.baselines import fuse_f5_rule_weighted_corrected
    from meeting_pipeline.fusion.confusion_network import build_confusion_network
    from meeting_pipeline.pipeline.speaker_turns import SpeakerTurn
    from meeting_pipeline.speaker.clustering import GlobalSpeakerClusterer
    from meeting_pipeline.speaker.encoder import create_speaker_encoder
    from meeting_pipeline.speaker.source_quality import SpeakerFusionPolicy

    t0 = time.perf_counter()
    prep_root = OUT / "cache/prepared_test_30"
    prepared = [read_json(p / "prepared.json") for p in sorted(prep_root.iterdir()) if (p / "prepared.json").is_file()]
    if not prepared:
        raise RuntimeError("Run wave1 speaker multisource first to populate prepared_test_30")

    cfg = load_config(ROOT / "configs/default.yaml")
    asr_base = cfg.asr.model_copy(
        update={"runtime": "mlx", "auto_backend": "mlx", "mlx_runtime_python": str(ROOT / ".venv-asr-mlx/bin/python")}
    )
    adapter = PhoWhisperAsrAdapter(asr_base, CACHE)

    emb_cache = OUT / "cache/speaker_embeddings"
    ecapa_enc = DiskCachedEncoder(
        create_speaker_encoder("speechbrain/spkrec-ecapa-voxceleb", "0f99f2d0ebe89ac095bcc5903c4dd8f72b367286", CACHE),
        emb_cache,
        "speechbrain/spkrec-ecapa-voxceleb@0f99f2d0ebe89ac095bcc5903c4dd8f72b367286",
    )
    wes_enc = DiskCachedEncoder(
        create_speaker_encoder("pyannote/wespeaker-voxceleb-resnet34-LM", "837717ddb9ff5507820346191109dc79c958d614", CACHE),
        emb_cache,
        "pyannote/wespeaker-voxceleb-resnet34-LM@837717ddb9ff5507820346191109dc79c958d614",
    )

    configs_e2e = [
        {
            "name": "C1_legacy_ecapa_transcript_f5",
            "encoder": ecapa_enc,
            "cluster_threshold": 0.40,
            "assign_threshold": 0.35,
            "assign_margin": 0.05,
            "asr_cfg": asr_base.model_copy(update={"fusion_mode": "transcript", "routing_mode": "adaptive", "max_verification_sources": 2}),
        },
        {
            "name": "C2_wespeaker_mlx_transcript_f5",
            "encoder": wes_enc,
            "cluster_threshold": 0.50,
            "assign_threshold": 0.41430566012859343,
            "assign_margin": 0.10853255093097687,
            "asr_cfg": asr_base.model_copy(update={"fusion_mode": "transcript", "routing_mode": "adaptive", "max_verification_sources": 3}),
        },
        {
            "name": "C3_wespeaker_mlx_audio_afftdn",
            "encoder": wes_enc,
            "cluster_threshold": 0.50,
            "assign_threshold": 0.41430566012859343,
            "assign_margin": 0.10853255093097687,
            "asr_cfg": asr_base.model_copy(update={"fusion_mode": "audio", "audio_denoise": "afftdn", "max_verification_sources": 3}),
        },
    ]

    summary_rows = []
    case_rows = []

    with tempfile.TemporaryDirectory() as tmpdir:
        asr_cache = AsrCache(Path(tmpdir) / "asr_cache", enabled=True)
        for c in configs_e2e:
            log(f"[Core E2E] Running {c['name']} on {len(prepared)} test meetings...")
            for m in prepared:
                ts = time.perf_counter()
                aligned = {sid: sf.read(p, dtype="float32")[0] for sid, p in m["aligned_paths"].items()}
                turns = [SpeakerTurn(**t) for t in m["detected_turns"]]
                clusterer = GlobalSpeakerClusterer(
                    c["encoder"],
                    cluster_threshold=c["cluster_threshold"],
                    assign_threshold=c["assign_threshold"],
                    assign_margin=c["assign_margin"],
                    fusion_policy=SpeakerFusionPolicy.P2_EMBEDDING_FUSION,
                )
                assignments, _, spk_sum = clusterer.cluster_and_identify(
                    turns, aligned, 16000, [], sync_metadata=m["sync_metadata"]
                )
                single_turns = sorted([t for t in turns if t.speaker_count == 1], key=lambda x: x.start_sec)
                paired_labels = []
                paired_preds = []
                pred_clusters = set()
                hyp_texts = []
                for idx, t in enumerate(single_turns):
                    item = assignments[t.turn_id]
                    if item.meeting_speaker_id:
                        pred_clusters.add(item.meeting_speaker_id)
                    gt = _ref_label(t.start_sec, t.end_sec, m["turns_ref"])
                    if gt and item.meeting_speaker_id:
                        paired_labels.append(gt)
                        paired_preds.append(item.meeting_speaker_id)

                    prev_b = single_turns[idx - 1].end_sec if idx > 0 else None
                    next_b = single_turns[idx + 1].start_sec if idx + 1 < len(single_turns) else None
                    hyps, _ = transcribe_turn_adaptive(
                        m["id"], t.turn_id, t.start_sec, t.end_sec, aligned, m["sync_metadata"], adapter, c["asr_cfg"], 16000, prev_b, next_b, cache=asr_cache
                    )
                    if c["asr_cfg"].fusion_mode == "audio":
                        txt = next((h.text for h in hyps.values() if h.asr_status == "transcribed"), "")
                    else:
                        bins = build_confusion_network(hyps)
                        txt, _ = fuse_f5_rule_weighted_corrected(bins, hyps)
                    if txt.strip():
                        hyp_texts.append(txt.strip())

                ref_doc = normalize_vietnamese_text(" ".join(rt["reference"] for rt in m["turns_ref"]))
                hyp_doc = normalize_vietnamese_text(" ".join(hyp_texts))
                case_rows.append(
                    {
                        "config": c["name"],
                        "meeting": m["id"],
                        "condition": m["condition"],
                        "device_count": m["device_count"],
                        "pairwise_f1": _pairwise_f1(paired_labels, paired_preds) if len(paired_labels) >= 2 else 0.0,
                        "count_err": abs(len(pred_clusters) - len(m["speakers"])),
                        "wer": float(jiwer.wer([ref_doc], [hyp_doc])),
                        "cer": float(jiwer.cer([ref_doc], [hyp_doc])),
                        "ref_doc": ref_doc,
                        "hyp_doc": hyp_doc,
                        "wall_sec": round(time.perf_counter() - ts, 3),
                    }
                )

            for subset_name, fn in [
                ("all_30", lambda r: True),
                ("easy_10", lambda r: r["condition"] == "easy"),
                ("moderate_10", lambda r: r["condition"] == "moderate"),
                ("stress_10", lambda r: r["condition"] == "stress"),
                ("1mic_10", lambda r: r["device_count"] == 1),
                ("2mic_10", lambda r: r["device_count"] == 2),
                ("4mic_10", lambda r: r["device_count"] == 4),
            ]:
                sel = [r for r in case_rows if r["config"] == c["name"] and fn(r)]
                refs = [r["ref_doc"] for r in sel]
                hyps = [r["hyp_doc"] for r in sel]
                summary_rows.append(
                    {
                        "config": c["name"],
                        "subset": subset_name,
                        "meetings": len(sel),
                        "mean_pairwise_f1": round(float(np.mean([r["pairwise_f1"] for r in sel])), 4),
                        "mean_speaker_count_error": round(float(np.mean([r["count_err"] for r in sel])), 3),
                        "corpus_wer": round(float(jiwer.wer(refs, hyps)), 4),
                        "corpus_cer": round(float(jiwer.cer(refs, hyps)), 4),
                        "mean_wall_sec": round(float(np.mean([r["wall_sec"] for r in sel])), 3),
                    }
                )

    out_dir = OUT / "wave2/core_e2e"
    write_csv(out_dir / "summary.csv", summary_rows)
    write_csv(out_dir / "per_meeting.csv", case_rows)
    write_json(
        out_dir / "results.json",
        {
            "benchmark": "wave2_core_e2e_30_meetings",
            "elapsed_sec": round(time.perf_counter() - t0, 2),
            "peak_rss_mb": round(rss_mb(), 2),
            "summary": summary_rows,
        },
    )
    log(f"[Core E2E] Done in {time.perf_counter() - t0:.2f}s")


if __name__ == "__main__":
    main()

