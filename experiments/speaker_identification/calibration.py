"""Calibration and threshold optimization on development split."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from experiments.speaker_identification.classifiers.base import BaseClassifier
from experiments.speaker_identification.contracts import EpisodeManifestRecord
from experiments.speaker_identification.metrics import compute_open_set_metrics


def evaluate_episode_with_thresholds(
    ep: EpisodeManifestRecord,
    embeddings_cache: dict[str, np.ndarray],
    classifier: BaseClassifier,
    score_threshold: float,
    margin_threshold: float,
) -> dict[str, Any]:
    """Evaluate one episode with given classifier and threshold settings."""
    # Build support embeddings
    support_embs: dict[str, list[np.ndarray]] = {}
    for spk_id, samples in ep.support_utterances.items():
        support_embs[spk_id] = [embeddings_cache[s["utterance_id"]] for s in samples]

    classifier.fit(support_embs)

    y_true: list[str] = []
    y_pred: list[str] = []
    is_known: list[bool] = []

    for q in ep.query_utterances:
        emb = embeddings_cache[q["utterance_id"]]
        pred = classifier.predict(
            emb,
            score_threshold=score_threshold,
            margin_threshold=margin_threshold,
            is_open_set=(ep.protocol == "open_set"),
        )
        y_true.append(q["true_speaker_id"])
        y_pred.append(pred.predicted_speaker_id)
        is_known.append(bool(q.get("is_known", True)))

    if ep.protocol == "open_set":
        return compute_open_set_metrics(y_true, y_pred, is_known, ep.known_speakers)
    else:
        from experiments.speaker_identification.metrics import compute_closed_set_metrics

        return compute_closed_set_metrics(y_true, y_pred, ep.known_speakers)


def calibrate_thresholds_for_config(
    episodes: list[EpisodeManifestRecord],
    embeddings_cache: dict[str, np.ndarray],
    classifier: BaseClassifier,
    score_candidates: list[float],
    margin_candidates: list[float],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Find best score and margin threshold maximizing average open-set macro F1."""
    open_episodes = [ep for ep in episodes if ep.protocol == "open_set"]
    if not open_episodes:
        raise ValueError("Cannot calibrate without open-set episodes")

    all_search_records: list[dict[str, Any]] = []
    best_config: dict[str, Any] | None = None
    best_score: tuple[float, float, float] = (-1.0, -1.0, -1.0)  # (macro_f1, unk_recall, known_acc)

    for st in score_candidates:
        for mt in margin_candidates:
            f1_list: list[float] = []
            unk_rec_list: list[float] = []
            known_acc_list: list[float] = []
            acc_list: list[float] = []

            for ep in open_episodes:
                metrics = evaluate_episode_with_thresholds(
                    ep,
                    embeddings_cache,
                    classifier,
                    score_threshold=st,
                    margin_threshold=mt,
                )
                f1_list.append(float(metrics["macro_f1"]))
                unk_rec_list.append(float(metrics["unknown_rejection"]))
                known_acc_list.append(float(metrics["known_accuracy"]))
                acc_list.append(float(metrics["accuracy"]))

            mean_f1 = float(np.mean(f1_list))
            mean_unk_rec = float(np.mean(unk_rec_list))
            mean_known_acc = float(np.mean(known_acc_list))
            mean_acc = float(np.mean(acc_list))

            record = {
                "score_threshold": st,
                "margin_threshold": mt,
                "macro_f1": mean_f1,
                "unknown_rejection": mean_unk_rec,
                "known_accuracy": mean_known_acc,
                "accuracy": mean_acc,
            }
            all_search_records.append(record)

            curr_score = (mean_f1, mean_unk_rec, mean_known_acc)
            if curr_score > best_score:
                best_score = curr_score
                best_config = record

    if best_config is None:
        raise RuntimeError("No valid calibration configuration found")

    return best_config, all_search_records


def save_frozen_calibration(
    calibration_records: dict[str, Any],
    output_path: Path | str,
) -> str:
    """Save frozen calibration to JSON and return its SHA-256 hash."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    json_str = json.dumps(calibration_records, indent=2, ensure_ascii=False) + "\n"
    output_path.write_text(json_str, encoding="utf-8")

    return hashlib.sha256(json_str.encode("utf-8")).hexdigest()
