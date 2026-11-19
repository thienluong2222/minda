"""Wave 1-2: Multi-source speaker fusion (P0-P3) with WeSpeaker (E3) vs ECAPA (E1) vs WavLM (E4) on all 30 test meetings."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import sys
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
        self.hits = 0
        self.misses = 0

    def encode(self, waveform):
        import numpy as np

        h = hashlib.sha256(self.identity.encode() + np.asarray(waveform, dtype=np.float32).tobytes()).hexdigest()
        p = self.cache_dir / f"{h}.npy"
        if p.is_file():
            self.hits += 1
            return np.asarray(np.load(p), dtype=np.float32)
        self.misses += 1
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


def _ref_label(turn_start: float, turn_end: float, ref_turns: list[dict]) -> str | None:
    best_dur = 0.0
    best_spk = None
    for rt in ref_turns:
        ov = max(0.0, min(turn_end, rt["end_sec"]) - max(turn_start, rt["start_sec"]))
        if ov > best_dur:
            best_dur = ov
            best_spk = rt["speaker"]
    return best_spk if best_dur >= 0.5 * max(turn_end - turn_start, 1e-6) else None


def prepare_30_test_meetings() -> list[dict]:
    """Run synchronization + Pyannote shared segmentation + SpeakerTurnDetector once per test meeting."""
    import soundfile as sf
    from meeting_pipeline.adapters.pyannote_segmentation import PyannoteSegmentationAdapter
    from meeting_pipeline.audio.synchronization import synchronize_multi_source_audio
    from meeting_pipeline.config import load_config
    from meeting_pipeline.domain.contracts import VadConfig
    from meeting_pipeline.pipeline.speaker_turns import SpeakerTurn, SpeakerTurnDetector
    from meeting_pipeline.pipeline.stages.shared_segmentation import run_shared_pyannote_segmentation

    cfg = load_config(ROOT / "configs/default.yaml")
    seg_id = str(cfg.models["segmentation_id"])
    seg_rev = str(cfg.models["segmentation_revision"])
    seg_path = CACHE / ("models--" + seg_id.replace("/", "--")) / "snapshots" / seg_rev / "pytorch_model.bin"
    step_sec = float(cfg.segmentation.step_seconds)
    vad_cfg = VadConfig(
        backend="pyannote",
        threshold=float(cfg.segmentation.vad_threshold),
        min_speech_sec=float(cfg.segmentation.minimum_speech_ms) / 1000.0,
        min_silence_sec=float(cfg.segmentation.minimum_silence_ms) / 1000.0,
        merge_gap_sec=float(cfg.segmentation.merge_gap_ms) / 1000.0,
        padding_sec=float(cfg.segmentation.speech_pad_ms) / 1000.0,
    )
    adapter = PyannoteSegmentationAdapter(seg_path, step_seconds=step_sec, model_revision=seg_rev)
    detector = SpeakerTurnDetector(seg_path, step_seconds=step_sec, adapter=adapter)

    sim_test = [m for m in read_json(CB_DATA / "simulation/manifest.json") if m["split"] == "test"]
    prep_root = OUT / "cache/prepared_test_30"
    prep_root.mkdir(parents=True, exist_ok=True)
    prepared = []

    for m in sim_test:
        mdir = prep_root / m["id"]
        meta_file = mdir / "prepared.json"
        if meta_file.is_file():
            prepared.append(read_json(meta_file))
            continue

        mdir.mkdir(parents=True, exist_ok=True)
        (mdir / "aligned").mkdir(exist_ok=True)
        sigs = {s["id"]: sf.read(s["path"], dtype="float32")[0] for s in m["sources"]}
        aligned, sync_meta, ref_source = synchronize_multi_source_audio(
            sigs, 16000, reference_source_id="source-1", allow_drift=True
        )
        aligned_paths = {}
        for sid, wav in aligned.items():
            p = mdir / "aligned" / f"{sid}.wav"
            sf.write(p, wav, 16000, subtype="FLOAT")
            aligned_paths[sid] = p

        # Note simulation manifest turns were defined before sync padded/aligned relative to source-1 (offset=0)
        # Ensure reference turns shift if reference_source had offset, here source-1 has offset_sec=0.0
        dur = max(len(w) for w in aligned.values()) / 16000.0
        segments, cached_seg = run_shared_pyannote_segmentation(
            aligned_paths=aligned_paths,
            adapter=adapter,
            meeting_duration_sec=dur,
            vad_config=vad_cfg,
            meeting_id=m["id"],
            sync_metadata=sync_meta,
            run_dir=mdir,
        )
        turns = detector.detect(
            aligned_paths,
            segments,
            ref_source,
            dur,
            cached_results=cached_seg,
            sync_metadata=sync_meta,
        )
        # Filter turns serialized cleanly
        turn_dicts = [dataclasses.asdict(t) for t in turns]
        entry = {
            "id": m["id"],
            "condition": m["condition"],
            "device_count": m["device_count"],
            "speakers": m["speakers"],
            "turns_ref": m["turns"],
            "aligned_paths": {k: str(v) for k, v in aligned_paths.items()},
            "sync_metadata": sync_meta,
            "detected_turns": turn_dicts,
        }
        write_json(meta_file, entry)
        prepared.append(entry)
    log(f"[Speaker P0-P3] Prepared {len(prepared)} test meetings")
    return prepared


def main() -> None:
    setup_root_src()
    import numpy as np
    import soundfile as sf
    from meeting_pipeline.application.speakers import SpeakerProfileInput
    from meeting_pipeline.pipeline.speaker_turns import SpeakerTurn
    from meeting_pipeline.speaker.clustering import GlobalSpeakerClusterer
    from meeting_pipeline.speaker.encoder import create_speaker_encoder
    from meeting_pipeline.speaker.source_quality import SpeakerFusionPolicy

    t0 = time.perf_counter()
    prepared = prepare_30_test_meetings()

    # Load clean VIVOS enrollment waveforms for VIVOS test speakers (k=3 per speaker)
    vivos = [json.loads(l) for l in (ROOT / "data/manifests/vivos.jsonl").read_text().splitlines() if l.strip()]
    enroll_by_spk = {}
    for r in vivos:
        if r["split"] == "test" and r.get("is_enrollment"):
            enroll_by_spk.setdefault(r["speaker_id"], []).append(ROOT / r["audio_path"])
    all_test_spks = sorted(enroll_by_spk.keys())

    encoders_cfg = [
        {
            "key": "E3_WeSpeaker",
            "model_id": "pyannote/wespeaker-voxceleb-resnet34-LM",
            "revision": "837717ddb9ff5507820346191109dc79c958d614",
            "cluster_threshold": 0.50,
            "assign_threshold": 0.41430566012859343,
            "assign_margin": 0.10853255093097687,
            "enrolled_threshold": 0.41430566012859343,
            "enrolled_margin": 0.10853255093097687,
        },
        {
            "key": "E1_ECAPA",
            "model_id": "speechbrain/spkrec-ecapa-voxceleb",
            "revision": "0f99f2d0ebe89ac095bcc5903c4dd8f72b367286",
            "cluster_threshold": 0.40,
            "assign_threshold": 0.35,
            "assign_margin": 0.05,
            "enrolled_threshold": 0.507577101389567,
            "enrolled_margin": 0.023166403174400337,
        },
        {
            "key": "E4_WavLM",
            "model_id": "microsoft/wavlm-base-plus-sv",
            "revision": "feb593a6c23c1cc3c7a500f5e2d900a99e2ecd0b",
            "cluster_threshold": 0.15,
            "assign_threshold": 0.15,
            "assign_margin": 0.0,
            "enrolled_threshold": 0.851118290424347,
            "enrolled_margin": 0.0,
        },
    ]

    summary_rows = []
    detail_rows = []
    emb_cache_dir = OUT / "cache/speaker_embeddings"

    from experiments.speaker_identification.run import get_encoder_by_id, load_benchmark_config
    sid_cfg = load_benchmark_config(ROOT / "experiments/speaker_identification/config.yaml")
    sid_cfg["paths"]["model_cache_dir"] = str(CACHE)

    for ecfg in encoders_cfg:
        log(f"[Speaker P0-P3] Running encoder {ecfg['key']}...")
        if ecfg["key"] == "E4_WavLM":
            enc_raw = get_encoder_by_id("E4", sid_cfg)
        else:
            enc_raw = create_speaker_encoder(
                model_id=ecfg["model_id"], revision=ecfg["revision"], cache_dir=CACHE
            )
        enc = DiskCachedEncoder(enc_raw, emb_cache_dir, f"{ecfg['model_id']}@{ecfg['revision']}")

        # Precompute enrollment k=3 normalized prototypes for all 19 VIVOS test speakers
        proto_map = {}
        for spk in all_test_spks:
            vecs = []
            for wp in sorted(enroll_by_spk[spk])[:3]:
                w, sr = sf.read(wp, dtype="float32")
                assert sr == 16000
                vecs.append(enc.encode(w))
            mean_v = np.mean(np.stack(vecs), axis=0)
            mean_v = mean_v / max(float(np.linalg.norm(mean_v)), 1e-8)
            proto_map[spk] = SpeakerProfileInput(spk, spk, mean_v.astype(np.float32))

        for profile_mode in ("none", "partial", "full"):
            for policy in SpeakerFusionPolicy:
                pf1_list = []
                cnt_err_list = []
                ambig_list = []
                known_ok = 0
                known_total = 0
                unk_reject_ok = 0
                unk_total = 0
                wall_list = []

                for m in prepared:
                    aligned = {sid: sf.read(p, dtype="float32")[0] for sid, p in m["aligned_paths"].items()}
                    turns = [SpeakerTurn(**t) for t in m["detected_turns"]]
                    distractors = [s for s in all_test_spks if s not in m["speakers"]][:2]
                    if profile_mode == "none":
                        profiles = []
                        known_set = set()
                    elif profile_mode == "partial":
                        # Enroll 2 of the 3 speakers + 2 distractors (so 1 true speaker remains unknown!)
                        kept = m["speakers"][:2]
                        profiles = [proto_map[s] for s in kept + distractors]
                        known_set = set(kept)
                    else:
                        profiles = [proto_map[s] for s in m["speakers"] + distractors]
                        known_set = set(m["speakers"])

                    ts = time.perf_counter()
                    clusterer = GlobalSpeakerClusterer(
                        enc,
                        cluster_threshold=ecfg["cluster_threshold"],
                        assign_threshold=ecfg["assign_threshold"],
                        assign_margin=ecfg["assign_margin"],
                        enrolled_match_threshold=ecfg["enrolled_threshold"],
                        enrolled_margin=ecfg["enrolled_margin"],
                        fusion_policy=policy,
                    )
                    assignments, _, summary = clusterer.cluster_and_identify(
                        turns, aligned, 16000, profiles, sync_metadata=m["sync_metadata"]
                    )
                    wall_list.append(time.perf_counter() - ts)

                    single_turns = [t for t in turns if t.speaker_count == 1]
                    paired_labels = []
                    paired_preds = []
                    pred_clusters = set()
                    ambig = 0
                    for t in single_turns:
                        item = assignments[t.turn_id]
                        if item.speaker_status == "ambiguous":
                            ambig += 1
                        if item.meeting_speaker_id:
                            pred_clusters.add(item.meeting_speaker_id)
                        gt_spk = _ref_label(t.start_sec, t.end_sec, m["turns_ref"])
                        if gt_spk is None:
                            continue
                        if item.meeting_speaker_id:
                            paired_labels.append(gt_spk)
                            paired_preds.append(item.meeting_speaker_id)
                        if profile_mode != "none":
                            if gt_spk in known_set:
                                known_total += 1
                                if item.speaker_status == "identified" and item.speaker_id == gt_spk:
                                    known_ok += 1
                            else:
                                unk_total += 1
                                if item.speaker_status != "identified":
                                    unk_reject_ok += 1

                    pf1 = _pairwise_f1(paired_labels, paired_preds) if len(paired_labels) >= 2 else 0.0
                    cnt_err = abs(len(pred_clusters) - len(m["speakers"]))
                    amb_rate = ambig / max(len(single_turns), 1)
                    pf1_list.append(pf1)
                    cnt_err_list.append(cnt_err)
                    ambig_list.append(amb_rate)
                    detail_rows.append(
                        {
                            "encoder": ecfg["key"],
                            "profiles": profile_mode,
                            "policy": policy.value,
                            "meeting": m["id"],
                            "condition": m["condition"],
                            "device_count": m["device_count"],
                            "pairwise_f1": round(pf1, 4),
                            "count_err": cnt_err,
                            "ambiguous_rate": round(amb_rate, 4),
                        }
                    )

                # Multi-mic subset (>=2 mics) vs all 30 meetings
                multi_pf1 = [
                    r["pairwise_f1"]
                    for r in detail_rows
                    if r["encoder"] == ecfg["key"]
                    and r["profiles"] == profile_mode
                    and r["policy"] == policy.value
                    and r["device_count"] >= 2
                ]
                summary_rows.append(
                    {
                        "encoder": ecfg["key"],
                        "profiles": profile_mode,
                        "policy": policy.value,
                        "meetings": len(prepared),
                        "pairwise_f1_all30": round(float(np.mean(pf1_list)), 4),
                        "pairwise_f1_multimic20": round(float(np.mean(multi_pf1)), 4),
                        "mean_speaker_count_error": round(float(np.mean(cnt_err_list)), 3),
                        "ambiguous_rate": round(float(np.mean(ambig_list)), 4),
                        "known_id_acc": round(known_ok / known_total, 4) if known_total else None,
                        "unknown_reject_rate": round(unk_reject_ok / unk_total, 4) if unk_total else None,
                        "avg_cluster_wall_sec": round(float(np.mean(wall_list)), 4),
                    }
                )

    out_dir = OUT / "wave1/speaker_multisource"
    write_csv(out_dir / "summary.csv", summary_rows)
    write_csv(out_dir / "per_meeting.csv", detail_rows)
    write_json(
        out_dir / "results.json",
        {
            "benchmark": "wave1_speaker_multisource_p0_p3",
            "elapsed_sec": round(time.perf_counter() - t0, 2),
            "peak_rss_mb": round(rss_mb(), 2),
            "meetings": len(prepared),
            "summary": summary_rows,
        },
    )
    log(f"[Speaker P0-P3] Done in {time.perf_counter() - t0:.2f}s")


if __name__ == "__main__":
    main()
