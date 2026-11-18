"""Real algorithm execution on controlled synthetic inputs; no fabricated measurements."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.comparative_benchmark.common import (
    OUT,
    SEED,
    log,
    read_json,
    setup,
    write_csv,
    write_json,
)


def clustering_prediction(matrix, method, parameter):
    import numpy as np
    from sklearn.cluster import DBSCAN, HDBSCAN, SpectralClustering

    if method.startswith("ahc"):
        from meeting_pipeline.pipeline.speaker_turns import SpeakerTurn
        from meeting_pipeline.speaker.clustering import _constrained_groups

        turns = [
            SpeakerTurn(
                turn_id=str(i),
                speech_region_id=f"r{i}",
                start_sec=i * 4.0,
                end_sec=i * 4.0 + 3.5,
                track_id=f"track{i}",
                speaker_count=1,
            )
            for i in range(len(matrix))
        ]
        groups = _constrained_groups(
            turns, {str(i): v for i, v in enumerate(matrix)}, float(parameter)
        )
        labels = np.zeros(len(matrix), dtype=int)
        for label, group in enumerate(groups):
            for i in group:
                labels[int(i)] = label
        return labels
    if method == "spectral":
        affinity = np.maximum(matrix @ matrix.T, 0.0) ** float(parameter)
        degree = np.maximum(affinity.sum(axis=1), 1e-9)
        normalized = affinity / np.sqrt(degree[:, None] * degree[None, :])
        eigenvalues = np.linalg.eigvalsh(normalized)[::-1]
        upper = min(6, len(matrix) - 1)
        k = int(np.argmax(eigenvalues[:upper] - eigenvalues[1 : upper + 1])) + 1
        return (
            np.zeros(len(matrix), dtype=int)
            if k == 1
            else SpectralClustering(
                n_clusters=k, affinity="precomputed", assign_labels="kmeans", random_state=SEED
            ).fit_predict(affinity)
        )
    if method == "dbscan":
        labels = DBSCAN(eps=float(parameter), min_samples=2, metric="cosine").fit_predict(matrix)
    else:
        labels = HDBSCAN(
            min_cluster_size=2, min_samples=int(parameter), metric="cosine", algorithm="brute"
        ).fit_predict(matrix)
    # Noise points remain separate unknown identities, not an invented shared speaker.
    next_label = max(labels.max() + 1, 0)
    for i in np.where(labels == -1)[0]:
        labels[i] = next_label
        next_label += 1
    return labels


def cluster_metrics(truth, prediction):
    import numpy as np
    from scipy.optimize import linear_sum_assignment
    from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score

    gold = np.asarray(truth)
    pred = np.asarray(prediction)
    same_gold = gold[:, None] == gold[None, :]
    same_pred = pred[:, None] == pred[None, :]
    precision = float(np.mean((same_gold & same_pred).sum(axis=1) / same_pred.sum(axis=1)))
    recall = float(np.mean((same_gold & same_pred).sum(axis=1) / same_gold.sum(axis=1)))
    n = max(int(gold.max()), int(pred.max())) + 1
    cm = np.zeros((n, n), dtype=int)
    np.add.at(cm, (gold, pred), 1)
    left, right = linear_sum_assignment(-cm)
    return {
        "ari": float(adjusted_rand_score(gold, pred)),
        "nmi": float(normalized_mutual_info_score(gold, pred)),
        "bcubed_f1": 2 * precision * recall / max(precision + recall, 1e-9),
        "speaker_confusion_rate_oracle_turns": 1 - float(cm[left, right].sum()) / len(gold),
        "speaker_count_error": abs(len(set(gold)) - len(set(pred))),
    }


def speaker_clustering():
    import numpy as np

    samples = read_json(OUT / "speaker_synthetic/samples.json")
    manifests = read_json(OUT / "speaker/manifests.json")
    cases = []
    for split, count in (("validation", 9), ("test", 30)):
        speakers = sorted({q["speaker"] for e in manifests[f"vivos_{split}"] for q in e["queries"]})
        rng = np.random.default_rng(SEED + (1 if split == "validation" else 2))
        for i in range(count):
            condition = ("easy", "moderate", "stress")[i % 3]
            chosen = sorted(rng.choice(speakers, 3, replace=False).tolist())
            entries = []
            for label, speaker in enumerate(chosen):
                pool = [
                    key
                    for key, s in samples.items()
                    if s["speaker"] == speaker and s.get("condition") == condition
                ]
                for key in rng.choice(pool, 3, replace=False):
                    entries.append({"id": str(key), "label": label})
            rng.shuffle(entries)
            cases.append(
                {
                    "id": f"{split}_{i:03d}",
                    "split": split,
                    "condition": condition,
                    "entries": entries,
                }
            )
    write_json(OUT / "speaker_clustering/manifest.json", cases)
    parameters = {
        "ahc_calibrated": [0.2, 0.3, 0.4, 0.5],
        "spectral": [1.0, 2.0, 4.0, 8.0],
        "dbscan": [0.15, 0.25, 0.35, 0.45],
        "hdbscan": [1, 2, 3, 4],
    }
    all_rows = []
    summary = []
    frozen = []
    for encoder in ("E1", "E3", "E2", "E4", "E0"):
        raw = np.load(OUT / f"speaker_synthetic/{encoder}.npz", allow_pickle=False)
        embeddings = dict(zip(raw["ids"].tolist(), raw["vectors"], strict=True))
        for method, grid in {"ahc_current": [0.4], **parameters}.items():
            evaluated = []
            for parameter in grid:
                values = []
                for case in [c for c in cases if c["split"] == "validation"]:
                    matrix = np.stack([embeddings[e["id"]] for e in case["entries"]])
                    truth = [e["label"] for e in case["entries"]]
                    values.append(
                        cluster_metrics(truth, clustering_prediction(matrix, method, parameter))[
                            "ari"
                        ]
                    )
                evaluated.append((float(np.mean(values)), parameter))
            _, parameter = max(evaluated, key=lambda x: (x[0], -float(x[1])))
            frozen.append(
                {
                    "encoder": encoder,
                    "method": method,
                    "parameter": parameter,
                    "selected_on": "validation"
                    if method != "ahc_current"
                    else "production_config_frozen",
                    "search": evaluated,
                }
            )
            for case in [c for c in cases if c["split"] == "test"]:
                matrix = np.stack([embeddings[e["id"]] for e in case["entries"]])
                truth = [e["label"] for e in case["entries"]]
                start = time.perf_counter()
                pred = clustering_prediction(matrix, method, parameter)
                all_rows.append(
                    {
                        "encoder": encoder,
                        "method": method,
                        "case": case["id"],
                        "condition": case["condition"],
                        "seconds": time.perf_counter() - start,
                        **cluster_metrics(truth, pred),
                    }
                )
            for condition in ("all", "easy", "moderate", "stress"):
                selected = [
                    r
                    for r in all_rows
                    if r["encoder"] == encoder
                    and r["method"] == method
                    and (condition == "all" or r["condition"] == condition)
                ]
                summary.append(
                    {
                        "encoder": encoder,
                        "method": method,
                        "condition": condition,
                        "cases": len(selected),
                        "parameter": parameter,
                        **{
                            key: float(np.mean([r[key] for r in selected]))
                            for key in (
                                "ari",
                                "nmi",
                                "bcubed_f1",
                                "speaker_confusion_rate_oracle_turns",
                                "speaker_count_error",
                                "seconds",
                            )
                        },
                    }
                )
        log(f"{encoder}: five speaker-clustering configurations finished")
    write_json(OUT / "speaker_clustering/calibration.json", frozen)
    write_json(OUT / "speaker_clustering/summary.json", summary)
    write_csv(OUT / "speaker_clustering/summary.csv", summary)
    write_csv(OUT / "speaker_clustering/per_case.csv", all_rows)
    write_json(
        OUT / "speaker_clustering/protocol.json",
        {
            "reference": "synthetic_turns_with_source_speaker_known",
            "embedding_inputs": "same_frozen_synthetic_speaker_vectors",
            "oracle_turn_boundaries": True,
            "cannot_link_constraints": "no_overlap_in_this_component_test; applied identically (none)",
            "not_full_DER": True,
            "hyperparameters": "four_candidates_each_on_validation; additionally_frozen_production_AHC",
            "no_true_speaker_count_passed_to_algorithms": True,
        },
    )


def make_fusion_cases():
    import numpy as np
    import soundfile as sf

    from meeting_pipeline.domain.contracts import SourceHypothesis, WordHypothesis
    from meeting_pipeline.fusion.confusion_network import build_confusion_network
    from meeting_pipeline.fusion.features import (
        compute_audio_quality_score,
        compute_transcript_quality_score,
        extract_acoustic_features,
    )

    rng = np.random.default_rng(SEED)
    meetings = read_json(OUT / "simulation/manifest.json")
    vocabulary = sorted(
        {
            word
            for case in meetings
            if case["split"] == "development"
            for t in case["turns"]
            for word in t["reference"].split()
        }
    )
    result = []
    for case in meetings:
        quality = {}
        for source in case["sources"]:
            wave, sr = sf.read(source["path"], dtype="float32")
            quality[source["id"]] = compute_audio_quality_score(extract_acoustic_features(wave, sr))
        for index, turn in enumerate(case["turns"]):
            hypotheses = {}
            for si, source in enumerate(case["sources"]):
                rate = {"easy": 0.07, "moderate": 0.17, "stress": 0.30}[
                    case["condition"]
                ] + si * 0.025
                tokens = []
                for word in turn["reference"].split():
                    draw = rng.random()
                    if draw < rate * 0.25:
                        continue
                    tokens.append(str(rng.choice(vocabulary)) if draw < rate else word)
                    if rng.random() < rate * 0.15:
                        tokens.append(str(rng.choice(vocabulary)))
                confidences = rng.uniform(0.45, 0.99, len(tokens))
                # Confidence is drawn without looking at whether a token is correct.
                mean = float(np.mean(confidences)) if len(tokens) else 0.5
                q = quality[source["id"]]
                words = [
                    WordHypothesis(
                        word=w,
                        start_sec=float(i) * 0.3,
                        end_sec=(i + 1) * 0.3,
                        asr_confidence=float(c),
                    )
                    for i, (w, c) in enumerate(zip(tokens, confidences, strict=True))
                ]
                hypotheses[source["id"]] = SourceHypothesis(
                    meeting_id=case["id"],
                    segment_id=str(index),
                    source_id=source["id"],
                    text=" ".join(tokens),
                    words=words,
                    audio_quality_score=q,
                    transcript_quality_score=compute_transcript_quality_score(q, mean, 0.5),
                    asr_features={"mean_confidence": mean},
                )
            bins = build_confusion_network(hypotheses)
            result.append(
                {
                    "meeting": case["id"],
                    "turn": index,
                    "split": case["split"],
                    "condition": case["condition"],
                    "sources": case["device_count"],
                    "reference": turn["reference"],
                    "hypotheses": hypotheses,
                    "bins": bins,
                }
            )
    write_json(
        OUT / "fusion/inputs.json",
        [
            {
                **{k: v for k, v in c.items() if k not in ("hypotheses", "bins")},
                "hypotheses": {key: h.model_dump() for key, h in c["hypotheses"].items()},
            }
            for c in result
        ],
    )
    return result


def fusion():
    import jiwer
    import numpy as np

    from meeting_pipeline.fusion import baselines as functions
    from meeting_pipeline.fusion.alignment import EPSILON_TOKEN
    from meeting_pipeline.fusion.model import LearnedFusionModel

    cases = make_fusion_cases()
    features = []
    labels = []
    for case in [c for c in cases if c["split"] == "development"]:
        bins = case["bins"]
        correctness = {}
        for source in case["hypotheses"]:
            indices = [
                i
                for i, b in enumerate(bins)
                if b.candidates.get(source, EPSILON_TOKEN) != EPSILON_TOKEN
            ]
            tokens = [bins[i].candidates[source] for i in indices]
            alignment = jiwer.process_words(case["reference"], " ".join(tokens))
            equal = {
                j
                for chunk in alignment.alignments[0]
                if chunk.type == "equal"
                for j in range(chunk.hyp_start_idx, chunk.hyp_end_idx)
            }
            for j, i in enumerate(indices):
                correctness[(i, source)] = int(j in equal)
        for i, b in enumerate(bins):
            for source, token in b.candidates.items():
                if token == EPSILON_TOKEN:
                    continue
                agree = sum(t == token for t in b.candidates.values()) / max(len(b.candidates), 1)
                features.append(
                    [
                        b.source_scores.get(source, 0.5),
                        b.confidences.get(source, 0.5),
                        0.05,
                        agree,
                        float(len(token)),
                        0.3,
                    ]
                )
                labels.append(correctness[(i, source)])

    def outputs(case, model):
        h, b = case["hypotheses"], case["bins"]
        return {
            "F0_FIXED": functions.fuse_f0_fixed(h)[0],
            "F1_BEST_SEGMENT": functions.fuse_f1_best_segment(h)[0],
            "F3_ROVER": functions.fuse_f3_rover(b)[0],
            "F4_ASR_WEIGHTED": functions.fuse_f4_asr_weighted(b)[0],
            "F5_RULE_WEIGHTED": functions.fuse_f5_rule_weighted(b)[0],
            "F5_RULE_WEIGHTED_CORRECTED": functions.fuse_f5_rule_weighted_corrected(b, h)[0],
            "F6_LEARNED": functions.fuse_f6_learned(b, model)[0],
        }

    options = []
    validation = [c for c in cases if c["split"] == "validation"]
    for regularization in (0.1, 1.0, 10.0):
        model = LearnedFusionModel(c_regularization=regularization, seed=SEED)
        model.fit(np.asarray(features, dtype=np.float32), np.asarray(labels, dtype=np.int32))
        value = jiwer.wer(
            [c["reference"] for c in validation],
            [outputs(c, model)["F6_LEARNED"] for c in validation],
        )
        options.append((value, regularization, model))
    _, regularization, model = min(options, key=lambda x: (x[0], x[1]))
    model.save(OUT / "fusion/learned_fusion_model.joblib")
    predictions = []
    for case in [c for c in cases if c["split"] == "test"]:
        for method, text in outputs(case, model).items():
            predictions.append(
                {
                    "meeting": case["meeting"],
                    "turn": case["turn"],
                    "condition": case["condition"],
                    "source_count": case["sources"],
                    "method": method,
                    "reference": case["reference"],
                    "prediction": text,
                }
            )
    summary = []
    for method in sorted({r["method"] for r in predictions}):
        for condition in ("all", "easy", "moderate", "stress"):
            rows = [
                r
                for r in predictions
                if r["method"] == method and (condition == "all" or r["condition"] == condition)
            ]
            score = jiwer.process_words(
                [r["reference"] for r in rows], [r["prediction"] for r in rows]
            )
            summary.append(
                {
                    "method": method,
                    "condition": condition,
                    "turns": len(rows),
                    "wer": score.wer,
                    "cer": jiwer.cer(
                        [r["reference"] for r in rows], [r["prediction"] for r in rows]
                    ),
                    "substitutions": score.substitutions,
                    "deletions": score.deletions,
                    "insertions": score.insertions,
                }
            )
    write_json(OUT / "fusion/summary.json", summary)
    write_csv(OUT / "fusion/summary.csv", summary)
    write_csv(OUT / "fusion/predictions.csv", predictions)
    write_json(
        OUT / "fusion/protocol.json",
        {
            "evidence": "real_fusion_algorithm_execution_on_scripted_transcript_corruptions",
            "not_actual_ASR_hypotheses": True,
            "acoustic_features": "measured_from_simulated_recordings_not_oracle_SNR",
            "token_confidence": "random_without_token_correctness_information",
            "F6_training_split": "development",
            "F6_training_labels": "reference_sequence_alignment_not_set_membership",
            "F6_C_selected_on": "validation",
            "selected_C": regularization,
            "training_samples": len(labels),
            "oracle_not_ranked": True,
            "application_artifacts_unchanged": True,
        },
    )
    log("Seven fusion algorithms finished")


def main():
    setup()
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["speaker-clustering", "fusion"])
    args = parser.parse_args()
    speaker_clustering() if args.command == "speaker-clustering" else fusion()


if __name__ == "__main__":
    main()
