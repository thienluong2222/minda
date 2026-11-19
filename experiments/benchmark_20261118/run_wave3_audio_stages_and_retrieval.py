"""Wave 3A: Audio intermediate stages (VAD/Seg, Overlap Separation + MLX ASR, Safe Merge) and Evidence Retrieval."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CB_DATA, CACHE, OUT, ROOT, SEED, log, read_json, rss_mb, setup_root_src, write_csv, write_json

BIN = 0.02


def _binary_metrics(tp: int, fp: int, fn: int, tn: int) -> dict[str, float]:
    prec = tp / max(tp + fp, 1)
    rec = tp / max(tp + fn, 1)
    f1 = 2 * tp / max(2 * tp + fp + fn, 1)
    return {
        "precision": round(prec, 4),
        "recall": round(rec, 4),
        "f1": round(f1, 4),
        "miss_rate": round(fn / max(tp + fn, 1), 4),
        "false_alarm_rate": round(fp / max(fp + tn, 1), 4),
    }


def benchmark_vad_and_segmentation() -> list[dict]:
    """Compare Pyannote segmentation-3.0 (production), Silero, FSMN-VAD, and CRDNN on 30 test meetings."""
    import numpy as np
    import soundfile as sf
    import torch

    from meeting_pipeline.adapters.pyannote_segmentation import PyannoteSegmentationAdapter
    import meeting_pipeline.audio.synchronization  # break circular import via audio.__init__
    from meeting_pipeline.pipeline.stages.shared_segmentation import (
        compute_pyannote_activity_curve,
        extract_pyannote_vad_intervals,
    )

    sim_test = [m for m in read_json(CB_DATA / "simulation/manifest.json") if m["split"] == "test"]
    rows = []

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        # 1. Production Pyannote segmentation-3.0 (speech VAD + overlap count >= 2)
        py_snap = next((CACHE / "models--pyannote--segmentation-3.0/snapshots").glob("*"))
        py_adapter = PyannoteSegmentationAdapter(py_snap / "pytorch_model.bin", step_seconds=2.5)
        py_adapter.load()

        # 2. Silero VAD
        from silero_vad import load_silero_vad

        silero_model = load_silero_vad()

        # 3. FSMN VAD
        from funasr import AutoModel

        fsmn_snap = next((CACHE / "models--funasr--fsmn-vad/snapshots").glob("*"))
        fsmn_model = AutoModel(
            model=str(fsmn_snap),
            device="cpu",
            disable_update=True,
            hub="hf",
            frontend_conf={"cmvn_file": str(fsmn_snap / "am.mvn")},
            ncpu=4,
        )

        # 4. CRDNN VAD
        from speechbrain.inference.VAD import VAD
        from speechbrain.utils.fetching import FetchConfig

        crdnn_snap = next((CACHE / "models--speechbrain--vad-crdnn-libriparty/snapshots").glob("*"))
        crdnn_model = VAD.from_hparams(
            source=str(crdnn_snap),
            savedir=str(tmp / "crdnn"),
            run_opts={"device": "cpu"},
            fetch_config=FetchConfig(allow_network=False),
        )

        for name in ("pyannote3_prod", "silero_vad", "fsmn_vad", "crdnn_vad"):
            tp = fp = fn = tn = 0
            ov_tp = ov_fp = ov_fn = ov_tn = 0
            total_segs = 0
            sub08_segs = 0
            total_wall = 0.0
            total_audio = 0.0
            for c in sim_test:
                src_path = Path(c["sources"][0]["path"])
                wave, sr = sf.read(src_path, dtype="float32")
                dur = len(wave) / sr
                total_audio += dur
                n = math.ceil(dur / BIN)
                centers = (np.arange(n) + 0.5) * BIN
                truth_cnt = np.zeros(n, dtype=np.int32)
                for rt in c["turns"]:
                    truth_cnt += (centers >= rt["start_sec"]) & (centers < rt["end_sec"])
                truth_vad = truth_cnt > 0

                t0 = time.perf_counter()
                with torch.inference_mode():
                    if name == "pyannote3_prod":
                        seg_res = py_adapter.segment_file(src_path, source_id="source-1")
                        curve = compute_pyannote_activity_curve(seg_res, dur, bin_sec=BIN)
                        # Overlap count curve
                        data = np.asarray(seg_res.data, dtype=np.float32)
                        step = float(seg_res.sliding_window.step)
                        cdur = float(seg_res.sliding_window.duration)
                        fc = (np.arange(data.shape[1]) + 0.5) * cdur / data.shape[1]
                        cnt_curve = np.zeros(len(curve), dtype=np.float64)
                        wt = np.zeros(len(curve), dtype=np.float64)
                        c_grid = (np.arange(len(curve)) + 0.5) * BIN
                        for idx_w, chunk in enumerate(data):
                            b0 = idx_w * step
                            msk = (c_grid >= b0) & (c_grid < b0 + cdur)
                            loc = c_grid[msk] - b0
                            tap = np.clip(np.minimum(loc, cdur - loc) / 1.25, 0.1, 1.0)
                            cnt_curve[msk] += np.interp(loc, fc, chunk.sum(axis=1)) * tap
                            wt[msk] += tap
                        cnt_curve = np.divide(cnt_curve, wt, out=np.zeros_like(cnt_curve), where=wt > 0)
                        intervals = extract_pyannote_vad_intervals(
                            curve, bin_sec=BIN, threshold=0.5, min_speech_ms=250, merge_gap_ms=400, speech_pad_ms=250, meeting_duration_sec=dur
                        )
                        pred_ov = np.floor(cnt_curve[:n] + 0.5).astype(int) >= 2
                        ov_tp += int(np.count_nonzero((truth_cnt >= 2) & pred_ov))
                        ov_fp += int(np.count_nonzero((truth_cnt < 2) & pred_ov))
                        ov_fn += int(np.count_nonzero((truth_cnt >= 2) & ~pred_ov))
                        ov_tn += int(np.count_nonzero((truth_cnt < 2) & ~pred_ov))
                    elif name == "silero_vad":
                        silero_model.reset_states()
                        probs = [
                            float(silero_model(torch.from_numpy(np.pad(wave[i : i + 512], (0, max(0, 512 - len(wave[i : i + 512]))))), 16000).item())
                            for i in range(0, len(wave), 512)
                        ]
                        curve = np.interp(centers, (np.arange(len(probs)) + 0.5) * 512 / 16000, probs).astype(np.float32)
                        intervals = extract_pyannote_vad_intervals(
                            curve, bin_sec=BIN, threshold=0.5, min_speech_ms=250, merge_gap_ms=400, speech_pad_ms=250, meeting_duration_sec=dur
                        )
                    elif name == "crdnn_vad":
                        prob = crdnn_model.get_speech_prob_chunk(torch.from_numpy(wave).unsqueeze(0)).reshape(-1).numpy()
                        curve = np.interp(centers, np.linspace(0, dur, len(prob)), prob).astype(np.float32)
                        intervals = extract_pyannote_vad_intervals(
                            curve, bin_sec=BIN, threshold=0.5, min_speech_ms=250, merge_gap_ms=400, speech_pad_ms=250, meeting_duration_sec=dur
                        )
                    else:
                        out = fsmn_model.generate(input=wave, cache={}, is_final=True, disable_pbar=True)
                        curve = np.zeros(n, dtype=np.float32)
                        for a_ms, b_ms in out[0].get("value", []):
                            curve[(centers >= a_ms / 1000.0) & (centers < b_ms / 1000.0)] = 1.0
                        intervals = extract_pyannote_vad_intervals(
                            curve, bin_sec=BIN, threshold=0.5, min_speech_ms=250, merge_gap_ms=400, speech_pad_ms=250, meeting_duration_sec=dur
                        )
                total_wall += time.perf_counter() - t0
                pred = np.zeros(n, dtype=bool)
                for s_a, s_b in intervals:
                    total_segs += 1
                    if (s_b - s_a) < 0.8:
                        sub08_segs += 1
                    pred |= (centers >= s_a) & (centers < s_b)
                tp += int(np.count_nonzero(truth_vad & pred))
                fp += int(np.count_nonzero(~truth_vad & pred))
                fn += int(np.count_nonzero(truth_vad & ~pred))
                tn += int(np.count_nonzero(~truth_vad & ~pred))

            row = {
                "task": "vad",
                "model": name,
                "meetings": len(sim_test),
                "audio_sec": round(total_audio, 2),
                "wall_sec": round(total_wall, 3),
                "rtf": round(total_wall / max(total_audio, 1e-6), 5),
                "segments": total_segs,
                "sub_08s_segments": sub08_segs,
                "sub_08s_rate": round(sub08_segs / max(total_segs, 1), 4),
                **_binary_metrics(tp, fp, fn, tn),
            }
            rows.append(row)
            if name == "pyannote3_prod":
                rows.append(
                    {
                        "task": "overlap_frame",
                        "model": name,
                        "meetings": len(sim_test),
                        "audio_sec": round(total_audio, 2),
                        "wall_sec": round(total_wall, 3),
                        "rtf": round(total_wall / max(total_audio, 1e-6), 5),
                        "segments": total_segs,
                        "sub_08s_segments": None,
                        "sub_08s_rate": None,
                        **_binary_metrics(ov_tp, ov_fp, ov_fn, ov_tn),
                    }
                )
            log(f"[Wave3A VAD] {name}: F1={row['f1']} sub08={row['sub_08s_rate']} rtf={row['rtf']}")
    return rows


def _si_sdr(ref, est):
    import numpy as np

    r = ref.astype(np.float64) - np.mean(ref)
    e = est.astype(np.float64) - np.mean(est)
    tgt = np.dot(e, r) * r / max(float(np.dot(r, r)), 1e-12)
    return float(10.0 * np.log10((np.dot(tgt, tgt) + 1e-12) / (np.dot(e - tgt, e - tgt) + 1e-12)))


def benchmark_overlap_separation() -> list[dict]:
    """Measure both acoustic PIT SI-SDR and real PhoWhisper-medium MLX ASR impact on 20 overlapping test clips."""
    import jiwer
    import numpy as np
    import torch
    from scipy.signal import resample_poly
    from speechbrain.inference.separation import SepformerSeparation
    from speechbrain.utils.fetching import FetchConfig

    from meeting_pipeline.adapters.phowhisper_asr import PhoWhisperAsrAdapter
    from meeting_pipeline.config import load_config
    from meeting_pipeline.data.vivos import normalize_vietnamese_text
    from meeting_pipeline.pipeline.overlap_separation import TwoSpeakerSeparator

    sep_test = [e for e in read_json(CB_DATA / "separation/manifest.json") if e["split"] == "test"]
    cfg = load_config(ROOT / "configs/default.yaml")
    asr_cfg = cfg.asr.model_copy(
        update={"runtime": "mlx", "auto_backend": "mlx", "mlx_runtime_python": str(ROOT / ".venv-asr-mlx/bin/python")}
    )
    adapter = PhoWhisperAsrAdapter(asr_cfg, CACHE)

    results = []
    # Unseparated baseline first
    mix_wers = []
    mix_best_wers = []
    base_sisdrs = []
    for e in sep_test:
        raw = np.load(e["path"])
        mix8 = raw["mixture"].astype(np.float32)
        targets8 = raw["targets"].astype(np.float32)
        base_sisdrs.append(float(np.mean([_si_sdr(t, mix8) for t in targets8])))
        mix16 = resample_poly(mix8, 2, 1).astype(np.float32)
        hyp = normalize_vietnamese_text(adapter.transcribe(mix16, 16000).text)
        refs = [normalize_vietnamese_text(r) for r in e["references"]]
        wers = [float(jiwer.wer([rf], [hyp])) for rf in refs]
        mix_wers.append(float(np.mean(wers)))
        mix_best_wers.append(float(min(wers)))
    results.append(
        {
            "model": "no_separation_mixture",
            "cases": len(sep_test),
            "si_sdr_db": round(float(np.mean(base_sisdrs)), 3),
            "si_sdr_improvement_db": 0.0,
            "pit_mean_wer": round(float(np.mean(mix_wers)), 4),
            "best_stream_wer": round(float(np.mean(mix_best_wers)), 4),
            "sep_rtf": 0.0,
        }
    )

    models_spec = [
        ("sepformer_whamr", "speechbrain/sepformer-whamr"),
        ("sepformer_wham", "speechbrain/sepformer-wham"),
        ("sepformer_libri2mix", "speechbrain/sepformer-libri2mix"),
        ("convtasnet", "mpariente/ConvTasNet_WHAM_sepclean"),
    ]
    with tempfile.TemporaryDirectory() as td:
        for key, mid in models_spec:
            snap = next((CACHE / ("models--" + mid.replace("/", "--")) / "snapshots").glob("*"))
            if key == "convtasnet":
                from asteroid.models import BaseModel

                wt = snap / "pytorch_model.bin"
                m = BaseModel.from_pretrained(str(wt)).eval()

                def infer(w, m=m):
                    with torch.inference_mode():
                        return m(torch.from_numpy(w).unsqueeze(0))[0].numpy()
            elif key == "sepformer_whamr":
                # Exercise exact production TwoSpeakerSeparator class on 16kHz input
                prod_sep = TwoSpeakerSeparator(
                    model_id=mid,
                    revision=snap.name,
                    model_cache_dir=CACHE,
                    runtime_dir=Path(td) / key,
                )

                def infer_prod(w8, sep=prod_sep):
                    w16 = resample_poly(w8, 2, 1).astype(np.float32)
                    st16 = sep.separate(w16, 0.0, len(w16) / 16000.0, context_sec=0.0)
                    return np.stack([resample_poly(s, 1, 2).astype(np.float32) for s in st16]), st16
            else:
                sb = SepformerSeparation.from_hparams(
                    source=str(snap),
                    savedir=str(Path(td) / key),
                    run_opts={"device": "cpu"},
                    fetch_config=FetchConfig(allow_network=False),
                )

                def infer(w, sb=sb):
                    with torch.inference_mode():
                        return sb.separate_batch(torch.from_numpy(w).unsqueeze(0))[0].transpose(0, 1).numpy()

            sisdr_list = []
            delta_list = []
            pit_wers = []
            best_wers = []
            rtfs = []
            for e in sep_test:
                raw = np.load(e["path"])
                mix8 = raw["mixture"].astype(np.float32)
                targets8 = raw["targets"].astype(np.float32)
                t0 = time.perf_counter()
                if key == "sepformer_whamr":
                    est8, est16 = infer_prod(mix8)
                else:
                    est8 = infer(mix8)
                    est16 = [resample_poly(est8[s], 2, 1).astype(np.float32) for s in range(2)]
                dt = time.perf_counter() - t0
                rtfs.append(dt / max(e["duration_sec"], 1e-6))

                ln = min(est8.shape[1], targets8.shape[1])
                sc_best = max(
                    np.mean([_si_sdr(targets8[i, :ln], est8[perm[i], :ln]) for i in range(2)])
                    for perm in itertools.permutations((0, 1))
                )
                base_sc = float(np.mean([_si_sdr(t[:ln], mix8[:ln]) for t in targets8]))
                sisdr_list.append(float(sc_best))
                delta_list.append(float(sc_best - base_sc))

                hyps16 = [normalize_vietnamese_text(adapter.transcribe(s16, 16000).text) for s16 in est16]
                refs = [normalize_vietnamese_text(r) for r in e["references"]]
                perm_wer = min(
                    float(np.mean([jiwer.wer([refs[0]], [hyps16[p[0]]]), jiwer.wer([refs[1]], [hyps16[p[1]]])]))
                    for p in itertools.permutations((0, 1))
                )
                pit_wers.append(perm_wer)
                best_wers.append(min(float(jiwer.wer([rf], [hp])) for rf in refs for hp in hyps16))

            results.append(
                {
                    "model": key,
                    "cases": len(sep_test),
                    "si_sdr_db": round(float(np.mean(sisdr_list)), 3),
                    "si_sdr_improvement_db": round(float(np.mean(delta_list)), 3),
                    "pit_mean_wer": round(float(np.mean(pit_wers)), 4),
                    "best_stream_wer": round(float(np.mean(best_wers)), 4),
                    "sep_rtf": round(float(np.mean(rtfs)), 3),
                }
            )
            log(f"[Wave3A Sep] {key}: dSI-SDR={results[-1]['si_sdr_improvement_db']}dB pit_WER={results[-1]['pit_mean_wer']}")
    if getattr(adapter, "_mlx_pipeline", None) is not None:
        adapter._mlx_pipeline.close()
    return results


def benchmark_safe_merge() -> list[dict]:
    """Compare no_merge vs safe_merge_speaker_turns on all 30 test meetings with WeSpeaker P2 + PhoWhisper-medium MLX."""
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
    from meeting_pipeline.pipeline.stages.safe_merge import safe_merge_speaker_turns
    from meeting_pipeline.speaker.clustering import GlobalSpeakerClusterer
    from meeting_pipeline.speaker.encoder import create_speaker_encoder
    from meeting_pipeline.speaker.source_quality import SpeakerFusionPolicy

    prep_root = OUT / "cache/prepared_test_30"
    prepared = [read_json(p / "prepared.json") for p in sorted(prep_root.iterdir()) if (p / "prepared.json").is_file()]
    cfg = load_config(ROOT / "configs/default.yaml")
    asr_cfg = cfg.asr.model_copy(
        update={
            "runtime": "mlx",
            "auto_backend": "mlx",
            "mlx_runtime_python": str(ROOT / ".venv-asr-mlx/bin/python"),
            "fusion_mode": "transcript",
            "routing_mode": "adaptive",
            "max_verification_sources": 3,
        }
    )
    adapter = PhoWhisperAsrAdapter(asr_cfg, CACHE)
    wes = create_speaker_encoder(
        "pyannote/wespeaker-voxceleb-resnet34-LM",
        "837717ddb9ff5507820346191109dc79c958d614",
        CACHE,
    )

    def ref_spks(s_t: float, e_t: float, refs: list[dict]) -> set[str]:
        return {r["speaker"] for r in refs if min(e_t, r["end_sec"]) - max(s_t, r["start_sec"]) >= 0.25}

    out_rows = []
    with tempfile.TemporaryDirectory() as td:
        asr_cache = AsrCache(Path(td) / "cache", enabled=True)
        for enabled in (False, True):
            refs_all = []
            hyps_all = []
            n_single_turns = 0
            n_sub08 = 0
            n_merged_multi = 0
            n_contam = 0
            asr_calls = 0
            t0 = time.perf_counter()

            for m in prepared:
                aligned = {sid: sf.read(p, dtype="float32")[0] for sid, p in m["aligned_paths"].items()}
                turns = [SpeakerTurn(**t) for t in m["detected_turns"]]
                clusterer = GlobalSpeakerClusterer(
                    wes,
                    cluster_threshold=float(cfg.identity.get("cluster_threshold", 0.50)),
                    assign_threshold=float(cfg.identity["identity_threshold"]),
                    assign_margin=float(cfg.identity["identity_margin"]),
                    fusion_policy=SpeakerFusionPolicy.P2_EMBEDDING_FUSION,
                )
                assignments, _, _ = clusterer.cluster_and_identify(
                    turns, aligned, 16000, [], sync_metadata=m["sync_metadata"]
                )
                merged = safe_merge_speaker_turns(
                    turns, assignments, max_merge_gap_sec=0.6, max_core_sec=float(cfg.asr.target_core_seconds), enabled=enabled
                )
                singles = sorted([t for t in merged if t.speaker_count == 1], key=lambda x: x.start_sec)
                texts = []
                for idx, mt in enumerate(singles):
                    n_single_turns += 1
                    if mt.duration_sec < 0.8:
                        n_sub08 += 1
                    if len(mt.sub_turn_ids) > 1:
                        n_merged_multi += 1
                        if len(ref_spks(mt.start_sec, mt.end_sec, m["turns_ref"])) > 1:
                            n_contam += 1
                    prev_b = singles[idx - 1].end_sec if idx > 0 else None
                    next_b = singles[idx + 1].start_sec if idx + 1 < len(singles) else None
                    hyps, meta = transcribe_turn_adaptive(
                        m["id"], mt.turn_id, mt.start_sec, mt.end_sec, aligned, m["sync_metadata"], adapter, asr_cfg, 16000, prev_b, next_b, cache=asr_cache
                    )
                    asr_calls += len(hyps)
                    bins = build_confusion_network(hyps)
                    txt, _ = fuse_f5_rule_weighted_corrected(bins, hyps)
                    if txt.strip():
                        texts.append(txt.strip())
                refs_all.append(normalize_vietnamese_text(" ".join(rt["reference"] for rt in m["turns_ref"])))
                hyps_all.append(normalize_vietnamese_text(" ".join(texts)))

            dt = time.perf_counter() - t0
            out_rows.append(
                {
                    "safe_merge_enabled": enabled,
                    "meetings": len(prepared),
                    "single_turns": n_single_turns,
                    "sub_08s_turns": n_sub08,
                    "sub_08s_rate": round(n_sub08 / max(n_single_turns, 1), 4),
                    "merged_groups": n_merged_multi,
                    "cross_speaker_contaminations": n_contam,
                    "asr_scheduled_sources": asr_calls,
                    "corpus_wer": round(float(jiwer.wer(refs_all, hyps_all)), 4),
                    "corpus_cer": round(float(jiwer.cer(refs_all, hyps_all)), 4),
                    "wall_sec": round(dt, 2),
                }
            )
            log(f"[Wave3A SafeMerge] enabled={enabled}: turns={n_single_turns} sub08={n_sub08} WER={out_rows[-1]['corpus_wer']}")
    if getattr(adapter, "_mlx_pipeline", None) is not None:
        adapter._mlx_pipeline.close()
    return out_rows


def _encode_texts(key: str, texts: list[str], is_query: bool) -> "np.ndarray":
    import numpy as np
    import torch
    from transformers import AutoModel, AutoTokenizer

    specs = {
        "e5_small": ("intfloat/multilingual-e5-small", "614241f622f53c4eeff9890bdc4f31cfecc418b3", "mean", True),
        "e5_base": ("intfloat/multilingual-e5-base", "d128750597153bb5987e10b1c3493a34e5a4502a", "mean", True),
        "minilm": ("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "e8f8c211226b894fcb81acc59f3b34ba3efd5f42", "mean", False),
        "bge_m3": ("BAAI/bge-m3", "5617a9f61b028005a4858fdac845db406aefb181", "cls", False),
    }
    mid, rev, pool, e5_prefix = specs[key]
    snap = CACHE / ("models--" + mid.replace("/", "--")) / "snapshots" / rev
    tok = AutoTokenizer.from_pretrained(snap, local_files_only=True)
    mdl = AutoModel.from_pretrained(snap, local_files_only=True).eval()
    prep = [f"{'query' if is_query else 'passage'}: {t}" for t in texts] if e5_prefix else texts
    vecs = []
    with torch.inference_mode():
        for i in range(0, len(prep), 32):
            batch = tok(prep[i : i + 32], padding=True, truncation=True, max_length=256, return_tensors="pt")
            out = mdl(**batch).last_hidden_state
            if pool == "cls":
                emb = out[:, 0]
            else:
                mask = batch["attention_mask"].unsqueeze(-1).float()
                emb = (out * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)
            emb = torch.nn.functional.normalize(emb, p=2, dim=1)
            vecs.append(emb.cpu().numpy().astype(np.float32))
    del mdl, tok
    return np.vstack(vecs)


def benchmark_retrieval_and_context() -> dict:
    """Compare BM25, TF-IDF, E5-small/base, MiniLM, BGE-M3, Hybrid RRF on text_manifest AND v2.1/test gold relations."""
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer

    from meeting_pipeline.minutes.evidence_retrieval import IndexedTurn, TurnSearchIndex, _tokenize
    from meeting_pipeline.minutes.transcript_context import context_spans

    def make_turns_from_units(units: list[dict], speaker_key: str = "speaker") -> list[IndexedTurn]:
        return [
            IndexedTurn(
                turn_id=u.get("turn_id", u.get("id", f"u{i}")),
                speaker_label=u.get(speaker_key, "speaker"),
                speaker_id=u.get("speaker_id"),
                start_sec=float(i * 2),
                end_sec=float(i * 2 + 1.5),
                text=u["text"],
                tokens=_tokenize(u["text"]),
                source_id="src-1",
                clip_path=None,
                asr_status="transcribed",
                needs_review=False,
                confidence=1.0,
                session_id=u.get("session_id", "session_0"),
                clock_id="clk_0",
            )
            for i, u in enumerate(units)
        ]

    # Suite A: 120 scripted queries on 30 test docs from 20261104/text/manifest.json
    text_test = [d for d in read_json(CB_DATA / "text/manifest.json") if d["split"] == "test"]
    suite_a_queries = []
    for d in text_test:
        units = d["units"]
        for q in d["queries"]:
            gold_idx = {i for i, u in enumerate(units) if u["topic"] == q["topic"]}
            suite_a_queries.append({"doc_id": d["id"], "units": units, "query": q["text"], "cand_idxs": list(range(len(units))), "gold_idxs": gold_idx})

    # Suite B: Hard multi-turn v2.1/test gold-relation retrieval (retrieve earlier target turn from source utterance!)
    v21_cases = [json.loads(l) for l in (ROOT / "artifacts/graph-synthetic-v2.1/test/references/cases.jsonl").read_text().splitlines() if l.strip()]
    suite_b_queries = []
    span_stats = {"cases": len(v21_cases), "total_turns": 0, "total_spans": 0}
    for c in v21_cases:
        turns = c["turns"]
        indexed = make_turns_from_units(turns)
        spans = context_spans(indexed)
        span_stats["total_turns"] += len(turns)
        span_stats["total_spans"] += len(spans)
        by_key = {ev["event_key"]: ev for ev in c["gold_events"]}
        turn_idx = {t["turn_id"]: i for i, t in enumerate(turns)}
        for rel in c["gold_relations"]:
            src_ev = by_key.get(rel["source_key"])
            tgt_ev = by_key.get(rel["target_key"])
            if not src_ev or not tgt_ev or src_ev["turn_id"] == tgt_ev["turn_id"]:
                continue
            s_i = turn_idx[src_ev["turn_id"]]
            t_i = turn_idx[tgt_ev["turn_id"]]
            cands = [i for i in range(s_i)] if t_i < s_i else [i for i in range(len(turns)) if i != s_i]
            if not cands:
                continue
            suite_b_queries.append({"doc_id": c["case_id"], "units": turns, "query": turns[s_i]["text"], "cand_idxs": cands, "gold_idxs": {t_i}})

    def eval_suite(items: list[dict], suite_name: str) -> list[dict]:
        # Pre-encode dense vectors cleanly
        unique_docs = {}
        for it in items:
            if it["doc_id"] not in unique_docs:
                unique_docs[it["doc_id"]] = [u["text"] for u in it["units"]]
        doc_keys = list(unique_docs.keys())
        all_passages = [txt for dk in doc_keys for txt in unique_docs[dk]]
        all_q_texts = [it["query"] for it in items]

        dense_cache = {}
        for enc in ("e5_small", "e5_base", "minilm", "bge_m3"):
            ts = time.perf_counter()
            p_vecs = _encode_texts(enc, all_passages, is_query=False)
            q_vecs = _encode_texts(enc, all_q_texts, is_query=True)
            dt = time.perf_counter() - ts
            # Slice per doc
            doc_mats = {}
            cur = 0
            for dk in doc_keys:
                n_u = len(unique_docs[dk])
                doc_mats[dk] = p_vecs[cur : cur + n_u]
                cur += n_u
            dense_cache[enc] = (doc_mats, q_vecs, dt)

        # Lexical caches per doc
        bm25_docs = {}
        tfidf_docs = {}
        for dk in doc_keys:
            units = [{"text": txt, "id": f"u{i}"} for i, txt in enumerate(unique_docs[dk])]
            turns = make_turns_from_units(units)
            bm25_docs[dk] = TurnSearchIndex(turns)
            vec = TfidfVectorizer().fit(unique_docs[dk])
            tfidf_docs[dk] = (vec, vec.transform(unique_docs[dk]))

        methods = ["bm25", "tfidf", "e5_small", "e5_base", "minilm", "bge_m3", "hybrid_rrf_e5_small"]
        out = []
        for method in methods:
            hits1 = hits2 = mrrs = rec3 = []
            hits1, hits2, mrrs, rec3 = [], [], [], []
            ts = time.perf_counter()
            for q_idx, it in enumerate(items):
                cands = it["cand_idxs"]
                gold = it["gold_idxs"]
                dk = it["doc_id"]
                if method == "bm25":
                    bm = bm25_docs[dk]
                    scores_map = {next(i for i, t in enumerate(bm.turns) if t is tr): sc for tr, sc in bm.search(it["query"], top_k=len(bm.turns))}
                    ranked = sorted(cands, key=lambda i: scores_map.get(i, 0.0), reverse=True)
                elif method == "tfidf":
                    vec, mat = tfidf_docs[dk]
                    qv = vec.transform([it["query"]])
                    sc = (mat @ qv.T).toarray().ravel()
                    ranked = sorted(cands, key=lambda i: float(sc[i]), reverse=True)
                elif method in dense_cache:
                    mat = dense_cache[method][0][dk]
                    qv = dense_cache[method][1][q_idx]
                    sc = mat @ qv
                    ranked = sorted(cands, key=lambda i: float(sc[i]), reverse=True)
                else:
                    # hybrid RRF of bm25 + e5_small
                    bm = bm25_docs[dk]
                    scores_map = {next(i for i, t in enumerate(bm.turns) if t is tr): sc for tr, sc in bm.search(it["query"], top_k=len(bm.turns))}
                    r_bm25 = sorted(cands, key=lambda i: scores_map.get(i, 0.0), reverse=True)
                    mat = dense_cache["e5_small"][0][dk]
                    qv = dense_cache["e5_small"][1][q_idx]
                    sc = mat @ qv
                    r_e5 = sorted(cands, key=lambda i: float(sc[i]), reverse=True)
                    rrf = {c: 0.0 for c in cands}
                    for rnk, c in enumerate(r_bm25):
                        rrf[c] += 1.0 / (60.0 + rnk + 1.0)
                    for rnk, c in enumerate(r_e5):
                        rrf[c] += 1.0 / (60.0 + rnk + 1.0)
                    ranked = sorted(cands, key=lambda i: rrf[i], reverse=True)

                hits1.append(float(ranked[0] in gold))
                hits2.append(float(any(c in gold for c in ranked[:2])))
                rec3.append(sum(1 for c in ranked[:3] if c in gold) / len(gold))
                pos = next((r_i for r_i, c in enumerate(ranked) if c in gold), None)
                mrrs.append(1.0 / (pos + 1) if pos is not None else 0.0)
            search_sec = time.perf_counter() - ts
            total_sec = search_sec + (dense_cache[method][2] if method in dense_cache else (dense_cache["e5_small"][2] if method == "hybrid_rrf_e5_small" else 0.0))
            out.append(
                {
                    "suite": suite_name,
                    "method": method,
                    "queries": len(items),
                    "hit_at_1": round(float(np.mean(hits1)), 4),
                    "hit_at_2": round(float(np.mean(hits2)), 4),
                    "recall_at_3": round(float(np.mean(rec3)), 4),
                    "mrr": round(float(np.mean(mrrs)), 4),
                    "elapsed_sec": round(total_sec, 3),
                }
            )
        return out

    rows_a = eval_suite(suite_a_queries, "text_manifest_120")
    rows_b = eval_suite(suite_b_queries, f"v21_gold_relations_{len(suite_b_queries)}")
    log(f"[Wave3A Retrieval] Suite A + Suite B ({len(suite_b_queries)} gold relation queries) done")
    return {"summary": rows_a + rows_b, "context_spans_v21": span_stats}


def main() -> None:
    setup_root_src()
    t0 = time.perf_counter()
    out_dir = OUT / "wave3/audio_stages_retrieval"
    out_dir.mkdir(parents=True, exist_ok=True)

    vad_rows = benchmark_vad_and_segmentation()
    write_csv(out_dir / "vad_summary.csv", vad_rows)

    sep_rows = benchmark_overlap_separation()
    write_csv(out_dir / "separation_summary.csv", sep_rows)

    merge_rows = benchmark_safe_merge()
    write_csv(out_dir / "safe_merge_summary.csv", merge_rows)

    ret_data = benchmark_retrieval_and_context()
    write_csv(out_dir / "retrieval_summary.csv", ret_data["summary"])

    write_json(
        out_dir / "results.json",
        {
            "benchmark": "wave3_audio_stages_and_retrieval",
            "elapsed_sec": round(time.perf_counter() - t0, 2),
            "peak_rss_mb": round(rss_mb(), 2),
            "vad_and_segmentation": vad_rows,
            "overlap_separation": sep_rows,
            "safe_merge": merge_rows,
            "retrieval": ret_data["summary"],
            "context_spans_v21": ret_data["context_spans_v21"],
        },
    )
    log(f"[Wave3A] ALL DONE in {time.perf_counter() - t0:.2f}s | peak_rss={rss_mb():.1f}MB")


if __name__ == "__main__":
    main()
