"""Replay the unchanged web pipeline with frozen versus validation-calibrated adapters."""

from __future__ import annotations

import argparse
import gc
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.comparative_benchmark.common import (
    CACHE,
    OUT,
    ROOT,
    SEED,
    WEB,
    log,
    read_json,
    setup,
    snapshot,
    verify_production_unchanged,
    write_csv,
    write_json,
)


def selected_asr():
    options = []
    for file in (OUT / "asr_mps_float16").glob("*/synthetic_validation_summary.json"):
        rows = [r for r in read_json(file) if r["condition"] in ("easy", "moderate", "stress")]
        if not rows:
            continue
        errors = sum(r["substitutions"] + r["deletions"] + r["insertions"] for r in rows)
        options.append((errors / sum(r["reference_words"] for r in rows), file.parent.name))
    return min(options)[1]


def evaluate(case, run_dir):
    import jiwer
    from pyannote.core import Annotation, Segment
    from pyannote.metrics.diarization import DiarizationErrorRate, JaccardErrorRate

    from meeting_pipeline.data.vivos import normalize_vietnamese_text

    result = read_json(run_dir / "timeline.json").get("segments", [])
    reference = Annotation()
    hypothesis = Annotation()
    for i, turn in enumerate(case["turns"]):
        reference[Segment(turn["start_sec"], turn["end_sec"]), str(i)] = turn["speaker"]
    for i, row in enumerate(result):
        if int(row.get("speaker_count", 1)) > 1:
            continue
        label = (
            row.get("meeting_speaker_id")
            or row.get("speaker_id")
            or row.get("speaker_label")
            or "unknown"
        )
        if row["end_sec"] > row["start_sec"]:
            hypothesis[Segment(row["start_sec"], row["end_sec"]), str(i)] = label
    full_der = float(DiarizationErrorRate(collar=0, skip_overlap=False)(reference, hypothesis))
    non_overlap_der = float(
        DiarizationErrorRate(collar=0, skip_overlap=True)(reference, hypothesis)
    )
    jer = float(JaccardErrorRate(collar=0, skip_overlap=False)(reference, hypothesis))
    ref = normalize_vietnamese_text(" ".join(t["reference"] for t in case["turns"]))
    hyp = normalize_vietnamese_text(" ".join(r.get("text", "") for r in result))
    wer = jiwer.process_words(ref, hyp)
    # Timestamp-aware missed coverage is reported separately from identity errors.
    overlap_sec = 0.0
    for i, a in enumerate(case["turns"]):
        for b in case["turns"][i + 1 :]:
            overlap_sec += max(
                0.0, min(a["end_sec"], b["end_sec"]) - max(a["start_sec"], b["start_sec"])
            )
    return {
        "case": case["id"],
        "condition": case["condition"],
        "sources": case["device_count"],
        "segments": len(result),
        "wer": wer.wer,
        "cer": jiwer.cer(ref, hyp),
        "substitutions": wer.substitutions,
        "deletions": wer.deletions,
        "insertions": wer.insertions,
        "der_with_overlap": full_der,
        "der_without_overlap": non_overlap_der,
        "jer": jer,
        "reference_overlap_sec": overlap_sec,
        "skipped_overlap_rows": sum(
            r.get("asr_status") == "not_run" and r.get("speaker_count", 1) > 1 for r in result
        ),
        "run_dir": str(run_dir),
        "reference_scope": "simulated_utterance_extents",
    }


def run(configuration):
    import numpy as np
    import soundfile as sf
    import torch

    from experiments.comparative_benchmark.asr import MODELS, make_adapter
    from experiments.speaker_identification.run import get_encoder_by_id, load_benchmark_config
    from meeting_pipeline.application.speakers import SpeakerProfileInput
    from meeting_pipeline.config import load_config
    from meeting_pipeline.pipeline.multi_source_fusion import MultiSourceFusionPipeline

    chosen_asr = selected_asr() if configuration == "selected_asr" else "phowhisper_medium"
    encoder_id = "E3" if configuration in ("wespeaker", "selected_asr") else "E1"
    if chosen_asr == "phowhisper_medium" and configuration == "selected_asr":
        write_json(
            OUT / "core_replay/selected_asr.json",
            {
                "status": "same_as_wespeaker_configuration",
                "selected_asr": chosen_asr,
                "selection_split": "synthetic_validation",
            },
        )
        return
    cfg = load_config(WEB / "configs/default.yaml").model_copy(deep=True)
    cfg.paths.model_cache_dir = CACHE
    cfg.paths.data_dir = OUT / "core_replay/shared_quality_cache"
    cfg.paths.database_path = cfg.paths.data_dir / "unused_legacy.sqlite"
    model_path = snapshot(MODELS[chosen_asr])
    cfg.asr.model_id = MODELS[chosen_asr]
    cfg.asr.model_revision = model_path.name
    benchmark_cfg = load_benchmark_config(ROOT / "experiments/speaker_identification/config.yaml")
    benchmark_cfg["paths"]["model_cache_dir"] = str(CACHE)
    encoder = get_encoder_by_id(encoder_id, benchmark_cfg)
    if hasattr(encoder, "runtime_dir"):
        encoder.runtime_dir = OUT / "runtime" / f"core_{encoder_id}"
    if configuration != "baseline":
        calibrated = next(
            r
            for r in read_json(OUT / f"speaker_synthetic/{encoder_id}_frozen_calibration.json")
            if r["classifier"] == "cosine_prototype" and r["k"] == 3
        )
        cfg.identity["identity_threshold"] = calibrated["score_threshold"]
        cfg.identity["identity_margin"] = calibrated["margin_threshold"]
        group = next(
            r
            for r in read_json(OUT / "speaker_clustering/calibration.json")
            if r["encoder"] == encoder_id and r["method"] == "ahc_calibrated"
        )
        cfg.identity["cluster_threshold"] = group["parameter"]
    cfg.identity["model_id"] = encoder.model_id
    cfg.identity["model_revision"] = encoder.model_revision
    adapter = make_adapter(chosen_asr, "mps", "float16")
    records = {
        r["utterance_id"]: r
        for r in map(json.loads, (ROOT / "data/manifests/vivos.jsonl").read_text().splitlines())
    }
    enrollment = read_json(ROOT / "data/manifests/enrollment_catalog.json")
    cases = [
        case
        for case in read_json(OUT / "simulation/manifest.json")
        if case["id"].startswith(("test_003_", "test_004_", "test_005_"))
    ]
    destination = OUT / "core_replay" / configuration
    write_json(
        destination / "conditions.json",
        {
            "configuration": configuration,
            "asr": chosen_asr,
            "device": "mps",
            "dtype": "float16",
            "encoder": encoder_id,
            "fusion": "F5_RULE_WEIGHTED_CORRECTED",
            "config": cfg.model_dump(mode="json"),
            "asr_cache": "shared_only_within_this_frozen_MPS_float16_replay; speed_not_compared",
            "selection_split": "validation_only",
            "production_source_untouched": True,
        },
    )
    summary = []
    for case in cases:
        profiles = []
        for speaker in case["speakers"]:
            waves = []
            vectors = []
            for utterance in enrollment[speaker][:3]:
                wave, sr = sf.read(ROOT / records[utterance]["audio_path"], dtype="float32")
                assert sr == 16000
                waves.append(wave)
                vectors.append(encoder.encode(wave))
            mean = np.mean(vectors, axis=0)
            mean /= max(float(np.linalg.norm(mean)), 1e-12)
            profiles.append(
                SpeakerProfileInput(
                    speaker_id=speaker,
                    display_name=speaker,
                    embedding=mean.astype(np.float32),
                    sample_waveforms=tuple(waves),
                )
            )
        torch.manual_seed(SEED)
        started = time.perf_counter()
        pipeline = MultiSourceFusionPipeline(cfg, asr_adapter=adapter, speaker_encoder=encoder)
        run_dir = pipeline.run(
            f"{configuration}_{case['id']}",
            [Path(source["path"]) for source in case["sources"]],
            profiles,
            fusion_method="F5_RULE_WEIGHTED_CORRECTED",
        )
        row = {
            "configuration": configuration,
            "asr": chosen_asr,
            "encoder": encoder_id,
            "seconds_with_possible_ASR_cache": time.perf_counter() - started,
            **evaluate(case, run_dir),
        }
        summary.append(row)
        write_json(destination / "summary.json", summary)
        write_csv(destination / "summary.csv", summary)
        assert verify_production_unchanged()["passed"]
        log(
            f"Core {configuration}/{case['id']}: WER={row['wer']:.3f} DER={row['der_with_overlap']:.3f}"
        )
        del pipeline
        gc.collect()


def main():
    setup()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--configuration",
        choices=["baseline", "calibrated_ecapa", "wespeaker", "selected_asr"],
        required=True,
    )
    args = parser.parse_args()
    run(args.configuration)


if __name__ == "__main__":
    main()
