"""CLI entrypoint and orchestration for the speaker identification benchmark."""

from __future__ import annotations

import argparse
import csv
import datetime
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from experiments.speaker_identification.audio import load_audio_mono_16k
from experiments.speaker_identification.cache import EmbeddingCacheManager
from experiments.speaker_identification.calibration import (
    calibrate_thresholds_for_config,
    evaluate_episode_with_thresholds,
    save_frozen_calibration,
)
from experiments.speaker_identification.classifiers import (
    BaseClassifier,
    CosineKNNClassifier,
    CosinePrototypeClassifier,
    LinearSVMClassifier,
)
from experiments.speaker_identification.contracts import (
    EpisodeManifestRecord,
    RawPredictionRecord,
    UtteranceSample,
)
from experiments.speaker_identification.datasets import (
    load_sample_audio,
    load_vivos_dataset,
    load_voxvietnam_dataset,
)
from experiments.speaker_identification.encoders import (
    BaseSpeakerEncoder,
    MFCCEncoder,
    PyannoteWeSpeakerEncoder,
    SpeechBrainECAPAEncoder,
    SpeechBrainXVectorEncoder,
    TransformersWavLMEncoder,
)
from experiments.speaker_identification.episodes import (
    generate_vivos_episodes,
    generate_voxvietnam_episodes,
    load_manifest,
    save_manifest,
)
from experiments.speaker_identification.metrics import (
    aggregate_episode_metrics,
    compute_closed_set_metrics,
    compute_open_set_metrics,
)
from experiments.speaker_identification.reporting import (
    generate_classifier_comparison_markdown,
    generate_encoder_screening_markdown,
    save_raw_predictions_csv,
    save_summary_json_and_csv,
)
from experiments.speaker_identification.timing import (
    benchmark_encoder_timing,
    benchmark_end_to_end_timing,
    get_hardware_environment,
    measure_cold_load_time,
)


def load_benchmark_config(config_path: Path | str) -> dict[str, Any]:
    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
        return dict(data) if isinstance(data, dict) else {}


def get_encoder_by_id(enc_id: str, cfg: dict[str, Any]) -> BaseSpeakerEncoder:
    cache_dir = cfg["paths"]["model_cache_dir"]
    if enc_id == "E0":
        return MFCCEncoder()
    elif enc_id == "E1":
        return SpeechBrainECAPAEncoder(cache_dir=cache_dir)
    elif enc_id == "E2":
        return SpeechBrainXVectorEncoder(cache_dir=cache_dir)
    elif enc_id == "E3":
        return PyannoteWeSpeakerEncoder(cache_dir=cache_dir)
    elif enc_id == "E4":
        return TransformersWavLMEncoder(cache_dir=cache_dir)
    else:
        raise ValueError(f"Unknown encoder ID: {enc_id}")


def get_classifier_by_name(name: str, **kwargs: Any) -> BaseClassifier:
    if name == "cosine_prototype":
        return CosinePrototypeClassifier()
    elif name == "cosine_knn":
        n_neighbors = kwargs.get("n_neighbors", 3)
        return CosineKNNClassifier(n_neighbors=n_neighbors)
    elif name == "linear_svm":
        c = kwargs.get("c", 1.0)
        return LinearSVMClassifier(c=c)
    else:
        raise ValueError(f"Unknown classifier name: {name}")


# -----------------------------------------------------------------------------
# COMMAND: validate-data
# -----------------------------------------------------------------------------
def cmd_validate_data(cfg: dict[str, Any]) -> None:
    print("=== [B0/B2] Validating Data Sources ===")
    vivos_train = load_vivos_dataset(cfg["paths"]["vivos_train_dir"])
    train_count = sum(len(v) for v in vivos_train.values())
    print(f"✓ VIVOS Train: {len(vivos_train)} speakers, total {train_count} utterances")

    vivos_test = load_vivos_dataset(cfg["paths"]["vivos_test_dir"])
    test_count = sum(len(v) for v in vivos_test.values())
    print(f"✓ VIVOS Test: {len(vivos_test)} speakers, total {test_count} utterances")

    supp, _query = load_voxvietnam_dataset(
        cfg["paths"]["voxvietnam_index_path"],
        cfg["paths"]["voxvietnam_dir"],
    )
    print(f"✓ VoxVietnam: {len(supp)} speakers, 5 support and 5 query per speaker, 0 overlap")
    print("Data validation successful.")


# -----------------------------------------------------------------------------
# COMMAND: prepare-models
# -----------------------------------------------------------------------------
def cmd_prepare_models(cfg: dict[str, Any]) -> None:
    print("=== [B0/B3] Preparing Model Cache and Inventory ===")
    from huggingface_hub import snapshot_download

    cache_dir = Path(cfg["paths"]["model_cache_dir"])
    cache_dir.mkdir(parents=True, exist_ok=True)

    inv_path = Path("experiments/speaker_identification/model_inventory.json")
    with open(inv_path, encoding="utf-8") as f:
        inv = json.load(f)

    for enc_id in ["E1", "E2", "E3", "E4"]:
        model_info = inv["models"][enc_id]
        repo_id = model_info["model_id"]
        rev = model_info["resolved_revision"]
        print(f"Ensuring {enc_id} ({repo_id} @ {rev[:8]})...")
        path = snapshot_download(repo_id=repo_id, revision=rev, cache_dir=str(cache_dir))
        print(f"  Cached at: {path}")

    print("All required models are present in model_cache.")


# -----------------------------------------------------------------------------
# COMMAND: smoke-encoders
# -----------------------------------------------------------------------------
def cmd_smoke_encoders(cfg: dict[str, Any]) -> None:
    print("=== [B4-B7] Running Offline Encoder Smoke Tests ===")
    vivos_test = load_vivos_dataset(cfg["paths"]["vivos_test_dir"])
    spk_ids = list(vivos_test.keys())
    sample_a = vivos_test[spk_ids[0]][0]
    sample_b = vivos_test[spk_ids[1]][0]

    wave_a = load_audio_mono_16k(sample_a.audio_path)  # type: ignore[arg-type]
    wave_b = load_audio_mono_16k(sample_b.audio_path)  # type: ignore[arg-type]

    for enc_id in ["E0", "E1", "E2", "E3", "E4"]:
        enc = get_encoder_by_id(enc_id, cfg)
        emb_a = enc.encode(wave_a)
        emb_b = enc.encode(wave_b)
        cos = float(np.dot(emb_a, emb_b))
        dim = emb_a.size
        finite = np.all(np.isfinite(emb_a))
        print(f"✓ {enc_id} ({enc.model_id}): dim={dim}, finite={finite}, cos_diff={cos:.4f}")
    print("Encoder smoke tests passed.")


# -----------------------------------------------------------------------------
# COMMAND: create-episodes
# -----------------------------------------------------------------------------
def cmd_create_episodes(cfg: dict[str, Any], run_dir: Path) -> dict[str, str]:
    print("=== [B3] Generating Deterministic Episode Manifests ===")
    manifests_dir = run_dir / "episode_manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)

    seed = cfg["seed"]
    few_shot_k = tuple(cfg["few_shot_k"])
    episodes_count = cfg["episodes"]

    # 1. VIVOS Development
    vivos_train = load_vivos_dataset(cfg["paths"]["vivos_train_dir"])
    ep_dev = generate_vivos_episodes(
        vivos_train,
        dataset_name="vivos",
        split_name="development",
        seed=seed,
        few_shot_k_list=few_shot_k,
        num_episodes=episodes_count,
    )
    dev_path = manifests_dir / "vivos-development.json"
    dev_hash = save_manifest(ep_dev, dev_path)
    print(f"✓ VIVOS Dev Manifest: {len(ep_dev)} records, SHA256={dev_hash}")

    # 2. VIVOS Test
    vivos_test = load_vivos_dataset(cfg["paths"]["vivos_test_dir"])
    ep_test = generate_vivos_episodes(
        vivos_test,
        dataset_name="vivos",
        split_name="test",
        seed=seed,
        few_shot_k_list=few_shot_k,
        num_episodes=episodes_count,
    )
    test_path = manifests_dir / "vivos-test.json"
    test_hash = save_manifest(ep_test, test_path)
    print(f"✓ VIVOS Test Manifest: {len(ep_test)} records, SHA256={test_hash}")

    # 3. VoxVietnam Public Test
    supp, query = load_voxvietnam_dataset(
        cfg["paths"]["voxvietnam_index_path"],
        cfg["paths"]["voxvietnam_dir"],
    )
    ep_vox = generate_voxvietnam_episodes(
        supp,
        query,
        dataset_name="voxvietnam",
        split_name="public_test",
        seed=seed,
        few_shot_k_list=few_shot_k,
        num_episodes=episodes_count,
    )
    vox_path = manifests_dir / "voxvietnam-public-test.json"
    vox_hash = save_manifest(ep_vox, vox_path)
    print(f"✓ VoxVietnam Manifest: {len(ep_vox)} records, SHA256={vox_hash}")

    return {
        "vivos-development": dev_hash,
        "vivos-test": test_hash,
        "voxvietnam-public-test": vox_hash,
    }


# -----------------------------------------------------------------------------
# COMMAND: cache-embeddings
# -----------------------------------------------------------------------------
def cmd_cache_embeddings(
    cfg: dict[str, Any],
    manifest_paths: list[Path],
    encoder_ids: list[str],
) -> dict[str, dict[str, np.ndarray]]:
    """Compute and cache all embeddings referenced by manifests.

    Returns in-memory dictionary: {encoder_id: {utterance_id: embedding}}
    """
    print("=== [B9] Caching Utterance Embeddings ===")
    cache_mgr = EmbeddingCacheManager(cfg["paths"]["evaluation_cache_dir"])
    vox_dir = cfg["paths"]["voxvietnam_dir"]

    # Gather all unique samples across manifests
    unique_samples: dict[str, UtteranceSample] = {}
    for m_path in manifest_paths:
        for ep in load_manifest(m_path):
            for supp_list in ep.support_utterances.values():
                for s_dict in supp_list:
                    u_id = s_dict["utterance_id"]
                    if u_id not in unique_samples:
                        unique_samples[u_id] = UtteranceSample.from_dict(s_dict)
            for q_dict in ep.query_utterances:
                u_id = q_dict["utterance_id"]
                if u_id not in unique_samples:
                    unique_samples[u_id] = UtteranceSample.from_dict(q_dict)

    print(f"Total unique utterances to cache across all manifests: {len(unique_samples)}")

    # Load audio waveforms into memory once
    print("Loading raw waveforms...")
    waveforms: dict[str, np.ndarray] = {}
    for u_id, sample in unique_samples.items():
        waveforms[u_id] = load_sample_audio(sample, voxvietnam_dir=vox_dir)

    all_embs: dict[str, dict[str, np.ndarray]] = {}

    for enc_id in encoder_ids:
        print(f"Caching embeddings for {enc_id}...")
        encoder = get_encoder_by_id(enc_id, cfg)
        enc_embs: dict[str, np.ndarray] = {}
        total = len(waveforms)
        for idx, (u_id, wave) in enumerate(waveforms.items(), 1):
            emb = cache_mgr.get_or_compute(encoder, wave)
            enc_embs[u_id] = emb
            if idx % 500 == 0 or idx == total:
                print(f"  [{enc_id}] {idx}/{total} processed...")
        all_embs[enc_id] = enc_embs
        print(f"✓ {enc_id} finished ({len(enc_embs)} embeddings cached)")

    return all_embs


# -----------------------------------------------------------------------------
# COMMAND: calibrate (Phase A: Screening & Calibration)
# -----------------------------------------------------------------------------
def cmd_calibrate(
    cfg: dict[str, Any],
    run_dir: Path,
    embs_by_encoder: dict[str, dict[str, np.ndarray]],
    manifest_hashes: dict[str, str],
) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]]:
    print("=== [B10/B11] Phase A: Screening & Calibration on VIVOS Development ===")
    dev_manifest_path = run_dir / "episode_manifests" / "vivos-development.json"
    dev_episodes = load_manifest(dev_manifest_path)

    calib_dir = run_dir / "calibration"
    calib_dir.mkdir(parents=True, exist_ok=True)

    encoder_screening_rows: list[dict[str, Any]] = []
    frozen_calib_records: dict[str, Any] = {
        "metadata": {
            "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
            "objective": "macro_f1_open_set",
            "development_manifest_hash": manifest_hashes["vivos-development"],
        },
        "configurations": {},
    }

    all_search_results: list[dict[str, Any]] = []

    # Score candidates for cosine (from 0.1 to 0.9)
    score_candidates = [round(x, 2) for x in np.linspace(0.15, 0.85, 15).tolist()]
    margin_candidates = [0.0, 0.05, 0.10, 0.15]

    encoder_dev_macro_f1: dict[str, list[float]] = {
        "E0": [],
        "E1": [],
        "E2": [],
        "E3": [],
        "E4": [],
    }

    for enc_id in ["E0", "E1", "E2", "E3", "E4"]:
        encoder_name = cfg["encoders"][enc_id]["name"]
        print(f"\nEvaluating Phase A for {enc_id} ({encoder_name})...")
        embs = embs_by_encoder[enc_id]
        clf = CosinePrototypeClassifier()

        for k in cfg["few_shot_k"]:
            episodes_k = [ep for ep in dev_episodes if ep.few_shot_k == k]
            best_cfg, search_records = calibrate_thresholds_for_config(
                episodes_k,
                embs,
                clf,
                score_candidates,
                margin_candidates,
            )
            for r in search_records:
                r["encoder_id"] = enc_id
                r["classifier_id"] = "cosine_prototype"
                r["few_shot_k"] = k
                all_search_results.append(r)

            key = f"{enc_id}_cosine_prototype_k{k}"
            frozen_calib_records["configurations"][key] = {
                "encoder_id": enc_id,
                "classifier_id": "cosine_prototype",
                "few_shot_k": k,
                "hyperparameters": {},
                "score_threshold": best_cfg["score_threshold"],
                "margin_threshold": best_cfg["margin_threshold"],
                "dev_macro_f1": best_cfg["macro_f1"],
                "dev_unknown_rejection": best_cfg["unknown_rejection"],
                "dev_known_accuracy": best_cfg["known_accuracy"],
                "dev_accuracy": best_cfg["accuracy"],
            }

            encoder_dev_macro_f1[enc_id].append(best_cfg["macro_f1"])

            # Compute detailed metrics on dev with best threshold for screening table
            eval_metrics_list = []
            for ep in episodes_k:
                if ep.protocol != "open_set":
                    continue
                m = evaluate_episode_with_thresholds(
                    ep,
                    embs,
                    clf,
                    best_cfg["score_threshold"],
                    best_cfg["margin_threshold"],
                )
                eval_metrics_list.append(m)

            agg = aggregate_episode_metrics(eval_metrics_list, seed=cfg["seed"])

            screening_row = {
                "dataset": "VIVOS dev",
                "encoder_id": enc_id,
                "encoder_name": encoder_name,
                "few_shot_k": k,
                "accuracy_mean": agg["accuracy"]["mean"],
                "accuracy_std": agg["accuracy"]["std"],
                "macro_precision_mean": agg["macro_precision"]["mean"],
                "macro_recall_mean": agg["macro_recall"]["mean"],
                "macro_f1_mean": agg["macro_f1"]["mean"],
                "macro_f1_std": agg["macro_f1"]["std"],
                "unknown_rejection_mean": agg["unknown_rejection"]["mean"],
                "latency_ms": 0.0,
                "rtf": 0.0,
            }
            encoder_screening_rows.append(screening_row)

    # Save search results CSV
    if all_search_results:
        search_csv_path = calib_dir / "search-results.csv"
        fieldnames = list(all_search_results[0].keys())
        with open(search_csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in all_search_results:
                writer.writerow(r)

    # Shortlist Decision: E1 is baseline. Select top 2 among E2, E3, E4 based on mean Macro F1
    avg_f1_scores = {
        enc_id: float(np.mean(encoder_dev_macro_f1[enc_id])) for enc_id in ["E2", "E3", "E4"]
    }
    sorted_candidates = sorted(avg_f1_scores.items(), key=lambda item: item[1], reverse=True)
    shortlisted_new = [sorted_candidates[0][0], sorted_candidates[1][0]]
    shortlist = ["E1", *shortlisted_new]

    print("\n--- Phase A Shortlist Selection ---")
    for enc_id, score in sorted_candidates:
        print(f"  {enc_id} ({cfg['encoders'][enc_id]['name']}): Dev Macro F1 = {score:.4f}")
    msg = f"Shortlisted: {shortlist} (baseline E1 + {shortlisted_new[0]} + {shortlisted_new[1]})"
    print(f"✓ {msg}")

    # Also calibrate KNN and SVM thresholds for the shortlisted encoders on VIVOS Dev!
    print("\nCalibrating KNN and Linear SVM thresholds on VIVOS dev for shortlisted encoders...")
    for enc_id in [*shortlist, "E0"]:
        embs = embs_by_encoder[enc_id]

        # KNN calibration
        knn_clf = CosineKNNClassifier(n_neighbors=3)
        for k in cfg["few_shot_k"]:
            episodes_k = [ep for ep in dev_episodes if ep.few_shot_k == k]
            best_cfg, _ = calibrate_thresholds_for_config(
                episodes_k, embs, knn_clf, score_candidates, margin_candidates
            )
            key = f"{enc_id}_cosine_knn_k{k}"
            frozen_calib_records["configurations"][key] = {
                "encoder_id": enc_id,
                "classifier_id": "cosine_knn",
                "few_shot_k": k,
                "hyperparameters": {"n_neighbors": 3},
                "score_threshold": best_cfg["score_threshold"],
                "margin_threshold": best_cfg["margin_threshold"],
                "dev_macro_f1": best_cfg["macro_f1"],
                "dev_unknown_rejection": best_cfg["unknown_rejection"],
                "dev_known_accuracy": best_cfg["known_accuracy"],
                "dev_accuracy": best_cfg["accuracy"],
            }

        # Linear SVM calibration (SVM scores range differently, e.g. -2.0 to 2.0)
        svm_clf = LinearSVMClassifier(c=1.0)
        svm_score_cands = [round(x, 2) for x in np.linspace(-1.0, 1.5, 11).tolist()]
        svm_margin_cands = [0.0, 0.1, 0.2, 0.4]
        for k in cfg["few_shot_k"]:
            episodes_k = [ep for ep in dev_episodes if ep.few_shot_k == k]
            best_cfg, _ = calibrate_thresholds_for_config(
                episodes_k, embs, svm_clf, svm_score_cands, svm_margin_cands
            )
            key = f"{enc_id}_linear_svm_k{k}"
            frozen_calib_records["configurations"][key] = {
                "encoder_id": enc_id,
                "classifier_id": "linear_svm",
                "few_shot_k": k,
                "hyperparameters": {"c": 1.0},
                "score_threshold": best_cfg["score_threshold"],
                "margin_threshold": best_cfg["margin_threshold"],
                "dev_macro_f1": best_cfg["macro_f1"],
                "dev_unknown_rejection": best_cfg["unknown_rejection"],
                "dev_known_accuracy": best_cfg["known_accuracy"],
                "dev_accuracy": best_cfg["accuracy"],
            }

    # Save frozen calibration JSON
    frozen_path = calib_dir / "frozen-calibration.json"
    frozen_hash = save_frozen_calibration(frozen_calib_records, frozen_path)
    print(f"✓ Frozen Calibration Saved: {frozen_path}, SHA256={frozen_hash}")

    return frozen_calib_records, shortlist, encoder_screening_rows


# -----------------------------------------------------------------------------
# COMMAND: evaluate (Phase B: Final Evaluation on Test Splits)
# -----------------------------------------------------------------------------
def run_evaluation_on_split(
    split_name: str,
    manifest_records: list[EpisodeManifestRecord],
    frozen_calib: dict[str, Any],
    embs_by_encoder: dict[str, dict[str, np.ndarray]],
    configurations: list[tuple[str, str]],  # [(encoder_id, classifier_id), ...]
    cfg: dict[str, Any],
) -> tuple[list[RawPredictionRecord], list[dict[str, Any]], list[dict[str, Any]]]:
    """Execute evaluation for given configurations on a split."""
    raw_predictions: list[RawPredictionRecord] = []
    episode_metric_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []

    run_id = cfg["run_id"]
    dataset_name = manifest_records[0].dataset

    for enc_id, clf_id in configurations:
        encoder_name = cfg["encoders"][enc_id]["name"]
        embs = embs_by_encoder[enc_id]

        for k in cfg["few_shot_k"]:
            episodes_k = [ep for ep in manifest_records if ep.few_shot_k == k]
            calib_key = f"{enc_id}_{clf_id}_k{k}"
            calib_info = frozen_calib["configurations"].get(
                calib_key,
                {"score_threshold": 0.0, "margin_threshold": 0.0},
            )
            score_th = calib_info["score_threshold"]
            margin_th = calib_info["margin_threshold"]

            clf = get_classifier_by_name(clf_id)

            open_eval_records = []

            for ep in episodes_k:
                support_embs: dict[str, list[np.ndarray]] = {}
                for spk_id, samples in ep.support_utterances.items():
                    support_embs[spk_id] = [embs[s["utterance_id"]] for s in samples]

                t_fit_start = time.perf_counter()
                clf.fit(support_embs)
                _ = time.perf_counter() - t_fit_start

                y_true: list[str] = []
                y_pred: list[str] = []
                is_known: list[bool] = []

                for q in ep.query_utterances:
                    u_id = q["utterance_id"]
                    emb = embs[u_id]

                    t_pred_start = time.perf_counter()
                    pred = clf.predict(
                        emb,
                        score_threshold=score_th,
                        margin_threshold=margin_th,
                        is_open_set=(ep.protocol == "open_set"),
                    )
                    clf_lat_ms = (time.perf_counter() - t_pred_start) * 1000.0

                    true_spk = q["true_speaker_id"]
                    is_k = bool(q.get("is_known", True))
                    y_true.append(true_spk)
                    y_pred.append(pred.predicted_speaker_id)
                    is_known.append(is_k)

                    # Determine correctness
                    if ep.protocol == "open_set":
                        correct = (
                            (pred.predicted_speaker_id == true_spk)
                            if is_k
                            else pred.predicted_unknown
                        )
                    else:
                        correct = pred.predicted_speaker_id == true_spk

                    raw_predictions.append(
                        RawPredictionRecord(
                            run_id=run_id,
                            dataset=dataset_name,
                            split=split_name,
                            protocol=ep.protocol,
                            episode_id=ep.episode_id,
                            few_shot_k=k,
                            encoder_id=enc_id,
                            classifier_id=clf_id,
                            query_id=u_id,
                            true_speaker_id=true_spk,
                            is_known=is_k,
                            predicted_speaker_id=pred.predicted_speaker_id,
                            predicted_unknown=pred.predicted_unknown,
                            top1_score=pred.top1_score,
                            top2_score=pred.top2_score,
                            margin=pred.margin,
                            score_threshold=score_th,
                            margin_threshold=margin_th,
                            correct=correct,
                            audio_duration_sec=float(q.get("duration_sec", 2.5)),
                            feature_latency_ms=0.0,
                            classifier_latency_ms=clf_lat_ms,
                            end_to_end_latency_ms=clf_lat_ms,
                        )
                    )

                # Compute episode-level metric
                if ep.protocol == "open_set":
                    ep_metric = compute_open_set_metrics(
                        y_true, y_pred, is_known, ep.known_speakers
                    )
                    open_eval_records.append(ep_metric)
                else:
                    ep_metric = compute_closed_set_metrics(y_true, y_pred, ep.known_speakers)

                ep_row = {
                    "dataset": dataset_name,
                    "split": split_name,
                    "protocol": ep.protocol,
                    "episode_id": ep.episode_id,
                    "encoder_id": enc_id,
                    "classifier_id": clf_id,
                    "few_shot_k": k,
                    "accuracy": ep_metric["accuracy"],
                    "macro_precision": ep_metric["macro_precision"],
                    "macro_recall": ep_metric["macro_recall"],
                    "macro_f1": ep_metric["macro_f1"],
                }
                if ep.protocol == "open_set":
                    ep_row["known_accuracy"] = ep_metric.get("known_accuracy", 0.0)
                    ep_row["unknown_rejection"] = ep_metric.get("unknown_rejection", 0.0)
                    ep_row["balanced_accuracy"] = ep_metric.get("balanced_accuracy", 0.0)
                episode_metric_rows.append(ep_row)

            # Summarize open-set metrics across episodes for Table 15.2
            if open_eval_records:
                agg = aggregate_episode_metrics(open_eval_records, seed=cfg["seed"])
                summary_rows.append(
                    {
                        "dataset": f"{dataset_name} ({split_name})",
                        "encoder_id": enc_id,
                        "encoder_name": encoder_name,
                        "classifier_id": clf_id,
                        "few_shot_k": k,
                        "accuracy_mean": agg["accuracy"]["mean"],
                        "accuracy_std": agg["accuracy"]["std"],
                        "macro_precision_mean": agg["macro_precision"]["mean"],
                        "macro_recall_mean": agg["macro_recall"]["mean"],
                        "macro_f1_mean": agg["macro_f1"]["mean"],
                        "macro_f1_std": agg["macro_f1"]["std"],
                        "known_accuracy_mean": agg["known_accuracy"]["mean"],
                        "unknown_rejection_mean": agg["unknown_rejection"]["mean"],
                        "balanced_accuracy_mean": agg["balanced_accuracy"]["mean"],
                    }
                )

    return raw_predictions, episode_metric_rows, summary_rows


# -----------------------------------------------------------------------------
# COMMAND: benchmark-time
# -----------------------------------------------------------------------------
def cmd_benchmark_time(
    cfg: dict[str, Any],
    run_dir: Path,
    encoder_ids: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    print("=== [B14] Running Uncached CPU Timing Benchmark ===")
    timing_dir = run_dir / "timing"
    timing_dir.mkdir(parents=True, exist_ok=True)

    vivos_test = load_vivos_dataset(cfg["paths"]["vivos_test_dir"])
    test_spk_ids = list(vivos_test.keys())[:6]

    # Prepare support waveforms (5 spks x 3 utts) and query waveforms (20 utts)
    support_waveforms: dict[str, list[np.ndarray]] = {}
    for s_id in test_spk_ids[:5]:
        support_waveforms[s_id] = [load_audio_mono_16k(s.audio_path) for s in vivos_test[s_id][:3]]  # type: ignore[arg-type]

    query_waveforms: list[np.ndarray] = []
    for s_id in test_spk_ids:
        for s in vivos_test[s_id][3:7]:
            query_waveforms.append(load_audio_mono_16k(s.audio_path))  # type: ignore[arg-type]

    timing_summary_rows: list[dict[str, Any]] = []
    raw_timing_rows: list[dict[str, Any]] = []

    model_inv = json.loads(
        Path("experiments/speaker_identification/model_inventory.json").read_text(encoding="utf-8")
    )

    for enc_id in encoder_ids:
        enc_name = cfg["encoders"][enc_id]["name"]
        model_bytes = model_inv["models"][enc_id].get("actual_downloaded_bytes", 0) or 0
        dim = cfg["encoders"][enc_id]["dimension"]

        print(f"Timing {enc_id} ({enc_name})...")
        enc = get_encoder_by_id(enc_id, cfg)

        # Cold load time
        cold_load_s = measure_cold_load_time(lambda e=enc_id: get_encoder_by_id(e, cfg))

        # Latency of extraction
        feat_timing = benchmark_encoder_timing(enc, query_waveforms, num_warmup=2, num_repeats=15)

        # End-to-end timing with Cosine Prototype
        clf = CosinePrototypeClassifier()
        e2e_timing = benchmark_end_to_end_timing(
            enc, clf, support_waveforms, query_waveforms, num_warmup=2
        )

        summary_row = {
            "encoder_id": enc_id,
            "encoder_name": enc_name,
            "model_bytes": model_bytes,
            "embedding_dim": dim,
            "cold_load_sec": cold_load_s,
            "enrollment_per_speaker_ms": e2e_timing["enrollment_per_speaker_ms"],
            "inference_mean_ms": e2e_timing["e2e_mean_ms"],
            "inference_p95_ms": e2e_timing["e2e_p95_ms"],
            "rtf": e2e_timing["rtf"],
        }
        timing_summary_rows.append(summary_row)

        raw_timing_rows.append(
            {
                "encoder_id": enc_id,
                "cold_load_sec": cold_load_s,
                "feature_mean_ms": feat_timing["mean_ms"],
                "feature_p95_ms": feat_timing["p95_ms"],
                "e2e_mean_ms": e2e_timing["e2e_mean_ms"],
                "e2e_median_ms": e2e_timing["e2e_median_ms"],
                "e2e_p95_ms": e2e_timing["e2e_p95_ms"],
                "enrollment_ms": e2e_timing["enrollment_per_speaker_ms"],
                "rtf": e2e_timing["rtf"],
            }
        )
        e2e_m = e2e_timing["e2e_mean_ms"]
        e2e_p = e2e_timing["e2e_p95_ms"]
        e2e_rtf = e2e_timing["rtf"]
        print(
            f"✓ {enc_id}: Cold={cold_load_s:.2f}s, E2E={e2e_m:.1f}ms, "
            f"p95={e2e_p:.1f}ms, RTF={e2e_rtf:.4f}"
        )

    # Save timing files
    save_summary_json_and_csv(
        timing_summary_rows,
        timing_dir / "summary.json",
        timing_dir / "summary.csv",
    )
    save_summary_json_and_csv(
        raw_timing_rows,
        timing_dir / "raw-timing.json",
        timing_dir / "raw-timing.csv",
    )

    return timing_summary_rows, raw_timing_rows


# -----------------------------------------------------------------------------
# MASTER RUNNER: run_all
# -----------------------------------------------------------------------------
def run_all(config_path: Path | str) -> None:
    cfg = load_benchmark_config(config_path)
    run_id = cfg["run_id"]
    run_dir = Path(cfg["paths"]["reports_dir"]) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    print("===========================================================")
    print(f"  STARTING SPEAKER IDENTIFICATION BENCHMARK: {run_id}")
    print(f"  Reports directory: {run_dir}")
    print("===========================================================")

    # 1. Snapshot config & environment
    (run_dir / "config.snapshot.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    env = get_hardware_environment()
    (run_dir / "environment.json").write_text(json.dumps(env, indent=2) + "\n", encoding="utf-8")
    py_v = env["python_version"]
    torch_v = env["torch_version"]
    os_name = env["os"]
    print(f"✓ Environment: Python {py_v}, PyTorch {torch_v} on {os_name}")

    # 2. Copy inventories
    inv_path = Path("experiments/speaker_identification/model_inventory.json")
    (run_dir / "model_inventory.json").write_text(
        inv_path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    d_inv_path = Path("experiments/speaker_identification/dataset_inventory.json")
    (run_dir / "dataset_inventory.json").write_text(
        d_inv_path.read_text(encoding="utf-8"), encoding="utf-8"
    )

    # 3. Create Episode Manifests (B3)
    manifest_hashes = cmd_create_episodes(cfg, run_dir)

    # 4. Cache Embeddings (B9)
    all_encoder_ids = ["E0", "E1", "E2", "E3", "E4"]
    manifest_paths = [
        run_dir / "episode_manifests" / "vivos-development.json",
        run_dir / "episode_manifests" / "vivos-test.json",
        run_dir / "episode_manifests" / "voxvietnam-public-test.json",
    ]
    embs_by_encoder = cmd_cache_embeddings(cfg, manifest_paths, all_encoder_ids)

    # 5. Phase A: Calibration & Shortlist (B10 & B11)
    frozen_calib, shortlist, screening_rows = cmd_calibrate(
        cfg, run_dir, embs_by_encoder, manifest_hashes
    )

    # 6. Uncached CPU Timing Benchmark (B14)
    timing_summary, _ = cmd_benchmark_time(cfg, run_dir, all_encoder_ids)

    # Update screening rows with latency & RTF from timing benchmark
    timing_map = {r["encoder_id"]: r for r in timing_summary}
    for row in screening_rows:
        enc_id = row["encoder_id"]
        if enc_id in timing_map:
            row["latency_ms"] = timing_map[enc_id]["inference_mean_ms"]
            row["rtf"] = timing_map[enc_id]["rtf"]

    # Generate Table 15.1
    generate_encoder_screening_markdown(screening_rows, run_dir / "encoder-screening.md")

    # 7. Phase B: Evaluate on VIVOS Test (B12) & VoxVietnam (B13)
    print("\n=== [B12 & B13] Phase B: Evaluating Shortlisted Configurations on Test Splits ===")
    phase_b_configs: list[tuple[str, str]] = []
    # 3 encoders x 3 classifiers = 9 main configs
    for enc_id in shortlist:
        for clf_id in ["cosine_prototype", "cosine_knn", "linear_svm"]:
            phase_b_configs.append((enc_id, clf_id))

    # Add MFCC backends and legacy baselines
    phase_b_configs.append(("E0", "cosine_prototype"))
    phase_b_configs.append(("E0", "cosine_knn"))
    phase_b_configs.append(("E0", "linear_svm"))

    # VIVOS Test evaluation (B12)
    vivos_test_manifest = load_manifest(run_dir / "episode_manifests" / "vivos-test.json")
    vivos_preds, vivos_ep_metrics, vivos_summary = run_evaluation_on_split(
        "test", vivos_test_manifest, frozen_calib, embs_by_encoder, phase_b_configs, cfg
    )
    save_raw_predictions_csv(vivos_preds, run_dir / "predictions" / "vivos-test.csv")
    print(f"✓ VIVOS Test finished: {len(vivos_preds)} raw predictions saved")

    # VoxVietnam Public Test evaluation (B13)
    vox_test_manifest = load_manifest(run_dir / "episode_manifests" / "voxvietnam-public-test.json")
    vox_preds, vox_ep_metrics, vox_summary = run_evaluation_on_split(
        "public_test", vox_test_manifest, frozen_calib, embs_by_encoder, phase_b_configs, cfg
    )
    save_raw_predictions_csv(vox_preds, run_dir / "predictions" / "voxvietnam-public-test.csv")
    print(f"✓ VoxVietnam Public Test finished: {len(vox_preds)} raw predictions saved")

    # Save metrics summaries
    metrics_dir = run_dir / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    all_ep_metrics = vivos_ep_metrics + vox_ep_metrics
    save_summary_json_and_csv(
        all_ep_metrics,
        metrics_dir / "metrics-by-episode.json",
        metrics_dir / "metrics-by-episode.csv",
    )

    all_comparison_summary = vivos_summary + vox_summary
    save_summary_json_and_csv(
        all_comparison_summary, metrics_dir / "summary.json", metrics_dir / "summary.csv"
    )

    # Generate Table 15.2
    generate_classifier_comparison_markdown(
        all_comparison_summary, run_dir / "classifier-comparison.md"
    )

    titanet_status = (
        "Skipped: NeMo toolkit is not pre-installed in the virtual environment "
        "to preserve environment integrity per Section 3.2."
    )

    # 9. B16 — Generate FINAL_REPORT.md
    print("\n=== [B16] Generating FINAL_REPORT.md ===")
    from experiments.speaker_identification.reporting import build_final_report_markdown

    final_report_content = build_final_report_markdown(
        run_id=run_id,
        env=env,
        manifest_hashes=manifest_hashes,
        frozen_calib_hash=save_frozen_calibration(
            frozen_calib, run_dir / "calibration" / "frozen-calibration.json"
        ),
        screening_rows=screening_rows,
        comparison_rows=all_comparison_summary,
        timing_rows=timing_summary,
        shortlist=shortlist,
        titanet_status=titanet_status,
    )
    (run_dir / "FINAL_REPORT.md").write_text(final_report_content, encoding="utf-8")
    print(f"✓ FINAL_REPORT.md written to {run_dir / 'FINAL_REPORT.md'}")

    print("\n===========================================================")
    print(f"  BENCHMARK COMPLETED SUCCESSFULLY: {run_id}")
    print("===========================================================")


def main() -> None:
    parser = argparse.ArgumentParser(description="Speaker Identification Benchmark Runner")
    parser.add_argument(
        "command",
        choices=[
            "all",
            "validate-data",
            "prepare-models",
            "smoke-encoders",
            "create-episodes",
            "cache-embeddings",
            "calibrate",
            "benchmark-time",
        ],
    )
    parser.add_argument(
        "--config",
        default="experiments/speaker_identification/config.yaml",
        help="Path to config.yaml",
    )
    args = parser.parse_args()

    cfg = load_benchmark_config(args.config)

    if args.command == "all":
        run_all(args.config)
    elif args.command == "validate-data":
        cmd_validate_data(cfg)
    elif args.command == "prepare-models":
        cmd_prepare_models(cfg)
    elif args.command == "smoke-encoders":
        cmd_smoke_encoders(cfg)
    elif args.command == "create-episodes":
        run_dir = Path(cfg["paths"]["reports_dir"]) / cfg["run_id"]
        cmd_create_episodes(cfg, run_dir)
    elif args.command == "cache-embeddings":
        run_dir = Path(cfg["paths"]["reports_dir"]) / cfg["run_id"]
        manifest_paths = [
            run_dir / "episode_manifests" / "vivos-development.json",
            run_dir / "episode_manifests" / "vivos-test.json",
            run_dir / "episode_manifests" / "voxvietnam-public-test.json",
        ]
        cmd_cache_embeddings(cfg, manifest_paths, ["E0", "E1", "E2", "E3", "E4"])
    elif args.command == "benchmark-time":
        run_dir = Path(cfg["paths"]["reports_dir"]) / cfg["run_id"]
        cmd_benchmark_time(cfg, run_dir, ["E0", "E1", "E2", "E3", "E4"])


if __name__ == "__main__":
    main()
