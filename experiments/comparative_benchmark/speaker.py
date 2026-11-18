"""Five encoders x four classifiers, enrollment-disjoint and speaker-disjoint splits."""

from __future__ import annotations

import argparse
import gc
import hashlib
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
    log,
    read_json,
    rss_mb,
    setup,
    sha,
    write_csv,
    write_json,
)


def make_manifests() -> dict:
    import numpy as np

    records = [
        json.loads(line) for line in (ROOT / "data/manifests/vivos.jsonl").read_text().splitlines()
    ]
    by_speaker = {}
    for row in records:
        by_speaker.setdefault(row["speaker_id"], []).append(row)
    result = {}
    for split in ("development", "validation", "test"):
        pools = {speaker: rows for speaker, rows in by_speaker.items() if rows[0]["split"] == split}
        rng = np.random.default_rng(SEED + {"development": 0, "validation": 1, "test": 2}[split])
        episodes = []
        for episode in range(30):
            speakers = rng.choice(sorted(pools), 10, replace=False).tolist()
            known, unknown = sorted(speakers[:5]), sorted(speakers[5:])
            support = {}
            queries = []
            for speaker in known + unknown:
                rows = pools[speaker]
                enrollment = [r for r in rows if r["is_enrollment"]]
                query = [r for r in rows if not r["is_enrollment"]]
                assert len(enrollment) >= 5 and len(query) >= 5
                if speaker in known:
                    support[speaker] = [
                        enrollment[int(i)]["utterance_id"]
                        for i in rng.choice(len(enrollment), 5, replace=False)
                    ]
                for i in rng.choice(len(query), 5, replace=False):
                    row = query[int(i)]
                    queries.append(
                        {"id": row["utterance_id"], "speaker": speaker, "known": speaker in known}
                    )
            for k in (1, 3, 5):
                episodes.append(
                    {
                        "episode": episode,
                        "k": k,
                        "known": known,
                        "unknown": unknown,
                        "support": {s: ids[:k] for s, ids in support.items()},
                        "queries": queries,
                    }
                )
        result[f"vivos_{split}"] = episodes
    from experiments.speaker_identification.datasets import load_voxvietnam_dataset
    from experiments.speaker_identification.episodes import generate_voxvietnam_episodes

    support, query = load_voxvietnam_dataset(ROOT / "data/external/voxvietnam/subset-index.json")
    vox = generate_voxvietnam_episodes(support, query, seed=SEED, num_episodes=30)
    result["voxvietnam_test"] = [
        {
            "episode": e.episode_id,
            "k": e.few_shot_k,
            "known": e.known_speakers,
            "unknown": e.unknown_speakers,
            "support": {
                s: [r["utterance_id"] for r in items] for s, items in e.support_utterances.items()
            },
            "queries": [
                {"id": q["utterance_id"], "speaker": q["true_speaker_id"], "known": q["is_known"]}
                for q in e.query_utterances
            ],
        }
        for e in vox
        if e.protocol == "open_set"
    ]
    samples = {
        r["utterance_id"]: {
            "audio_path": str(ROOT / r["audio_path"]),
            "speaker": r["speaker_id"],
            "file_sha256": r["audio_sha256"],
        }
        for r in records
    }
    for pool in (support, query):
        for speaker, items in pool.items():
            for item in items:
                samples[item.utterance_id] = {**item.to_dict(), "speaker": speaker}
    used = {q["id"] for episodes in result.values() for e in episodes for q in e["queries"]}
    used.update(
        i
        for episodes in result.values()
        for e in episodes
        for ids in e["support"].values()
        for i in ids
    )
    samples = {i: samples[i] for i in sorted(used)}
    # Audit all support/query intersections, speaker partitions, and known/unknown identities.
    for episodes in result.values():
        for e in episodes:
            assert not set(e["known"]) & set(e["unknown"])
            assert not {i for ids in e["support"].values() for i in ids} & {
                q["id"] for q in e["queries"]
            }
    split_speakers = [
        {q["speaker"] for e in result[f"vivos_{s}"] for q in e["queries"]}
        for s in ("development", "validation", "test")
    ]
    assert all(not a & b for i, a in enumerate(split_speakers) for b in split_speakers[i + 1 :])
    write_json(OUT / "speaker/manifests.json", result)
    write_json(OUT / "speaker/samples.json", samples)
    write_json(
        OUT / "speaker/leakage_audit.json",
        {
            "passed": True,
            "speaker_counts": [len(s) for s in split_speakers],
            "samples": len(samples),
            "support_query_disjoint": True,
            "support_from_reserved_enrollment": True,
            "seed": SEED,
            "episodes_per_k_per_dataset": 30,
            "test_status": "reused_public_test_not_unseen_real_meetings",
        },
    )
    return result


def extract(encoder_id: str, subdir: str = "speaker") -> None:
    import numpy as np
    import soundfile as sf

    from experiments.speaker_identification.cache import EmbeddingCacheManager
    from experiments.speaker_identification.contracts import UtteranceSample
    from experiments.speaker_identification.datasets import clear_parquet_cache, load_sample_audio
    from experiments.speaker_identification.run import get_encoder_by_id, load_benchmark_config

    folder = OUT / subdir
    samples = read_json(folder / "samples.json")
    cfg = load_benchmark_config(ROOT / "experiments/speaker_identification/config.yaml")
    cfg["paths"]["model_cache_dir"] = str(CACHE)
    encoder = get_encoder_by_id(encoder_id, cfg)
    if hasattr(encoder, "runtime_dir"):
        encoder.runtime_dir = OUT / "runtime" / encoder_id
    old_cache = EmbeddingCacheManager(ROOT / "data/evaluation_cache/speaker_embeddings")
    fresh_cache = EmbeddingCacheManager(OUT / "speaker/embedding_cache")
    ids, vectors = [], []
    timings, audits = [], []
    hits = computed = 0
    load_started = time.perf_counter()
    model_load_sec = None
    selected_timing = set(sorted(samples)[:20])
    for index, (sample_id, sample) in enumerate(samples.items()):
        if sample.get("audio_path"):
            # Corpus bytes are verified against the frozen VIVOS manifest.
            if sha(Path(sample["audio_path"])) != sample["file_sha256"]:
                raise ValueError(f"Corpus checksum mismatch: {sample_id}")
            wave, sr = sf.read(sample["audio_path"], dtype="float32")
            assert sr == 16000 and wave.ndim == 1
            if len(wave) < 8000:
                wave = np.pad(wave, (0, 8000 - len(wave)))
        else:
            record = UtteranceSample.from_dict(sample)
            wave = load_sample_audio(record, ROOT / "data/external/voxvietnam")
            if index % 10 == 0:
                clear_parquet_cache()
        cached = old_cache.get(encoder, wave)
        if cached is not None:
            digest = hashlib.sha256(
                np.ascontiguousarray(wave, dtype=np.float32).tobytes()
            ).hexdigest()
            _, meta_path = old_cache.get_cache_paths(encoder, digest)
            meta = read_json(meta_path)
            if any(
                meta.get(k) != getattr(encoder, k)
                for k in ("model_id", "model_revision", "sample_rate", "embedding_dimension")
            ):
                cached = None
        if cached is not None:
            hits += 1
        else:
            cached = fresh_cache.get(encoder, wave)
        if cached is None or sample_id in selected_timing:
            t = time.perf_counter()
            new = encoder.encode(wave)
            elapsed = time.perf_counter() - t
            if model_load_sec is None:
                model_load_sec = elapsed
                audits.append({"sample_id": sample_id, "first_call_including_load_sec": elapsed})
            else:
                timings.append(
                    {
                        "sample_id": sample_id,
                        "seconds": elapsed,
                        "duration_sec": len(wave) / 16000,
                        "rtf": elapsed / (len(wave) / 16000),
                    }
                )
            if cached is not None and sample_id in selected_timing:
                cosine = float(np.dot(new, cached) / (np.linalg.norm(new) * np.linalg.norm(cached)))
                audits.append({"sample_id": sample_id, "cached_fresh_cosine": cosine})
                if cosine < 0.999:
                    raise ValueError(
                        f"Cached/fresh embedding disagreement: {encoder_id} {sample_id} {cosine}"
                    )
            if cached is None:
                cached = new
                fresh_cache.put(encoder, wave, new)
                computed += 1
        ids.append(sample_id)
        vectors.append(cached)
        if index % 500 == 0:
            log(f"{encoder_id}: {index}/{len(samples)} embeddings; verified historical hits={hits}")
    np.savez_compressed(
        folder / f"{encoder_id}.npz", ids=np.asarray(ids), vectors=np.stack(vectors)
    )
    write_json(
        folder / f"{encoder_id}_timing.json",
        {
            "model_id": encoder.model_id,
            "revision": encoder.model_revision,
            "dimension": encoder.embedding_dimension,
            "sample_count": len(ids),
            "verified_historical_cache_hits": hits,
            "fresh_computations": computed,
            "first_call_including_load_sec": model_load_sec,
            "total_preparation_sec": time.perf_counter() - load_started,
            "peak_rss_mb": rss_mb(),
            "uncached_timing": timings,
            "cache_audit": audits,
        },
    )
    log(f"{encoder_id} ready; samples={len(ids)} peak_rss_mb={rss_mb():.0f}")


def episode_scores(embeddings, episode, classifier, parameter=1):
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.neighbors import KNeighborsClassifier
    from sklearn.svm import LinearSVC

    classes = episode["known"]
    support = np.stack([embeddings[i] for speaker in classes for i in episode["support"][speaker]])
    y = np.repeat(np.arange(len(classes)), episode["k"])
    queries = np.stack([embeddings[q["id"]] for q in episode["queries"]])
    if classifier == "cosine_prototype":
        centroids = np.stack(
            [np.mean([embeddings[i] for i in episode["support"][s]], axis=0) for s in classes]
        )
        centroids /= np.maximum(np.linalg.norm(centroids, axis=1, keepdims=True), 1e-12)
        scores = queries @ centroids.T
    elif classifier == "cosine_knn":
        model = KNeighborsClassifier(
            n_neighbors=min(int(parameter), len(support)), metric="cosine", weights="distance"
        ).fit(support, y)
        scores = model.predict_proba(queries)
        # Match the existing experiment backend: KNN votes choose the identity;
        # cosine distances, rather than saturated vote probabilities, reject strangers.
        predicted = model.predict(queries)
        class_similarity = np.stack(
            [(queries @ support[y == c].T).max(axis=1) for c in range(len(classes))], axis=1
        )
        ordered_similarity = np.sort(class_similarity, axis=1)
        best = ordered_similarity[:, -1]
        gap = best - ordered_similarity[:, -2]
        truth = np.array(
            [classes.index(q["speaker"]) if q["known"] else 5 for q in episode["queries"]]
        )
        return predicted, best, gap, truth
    elif classifier == "linear_svm":
        model = LinearSVC(C=float(parameter), random_state=SEED, max_iter=5000).fit(support, y)
        scores = model.decision_function(queries)
    elif classifier == "logistic_regression":
        model = LogisticRegression(C=float(parameter), random_state=SEED, max_iter=1000).fit(
            support, y
        )
        scores = model.predict_proba(queries)
    else:
        raise ValueError(classifier)
    order = np.argsort(scores, axis=1)
    top = order[:, -1]
    best = np.take_along_axis(scores, order[:, -1:], axis=1).ravel()
    second = np.take_along_axis(scores, order[:, -2:-1], axis=1).ravel()
    truth = np.array([classes.index(q["speaker"]) if q["known"] else 5 for q in episode["queries"]])
    return top, best, best - second, truth


def metric_arrays(truth, prediction):
    import numpy as np

    # Arrays: episodes x queries. Classes 0..4 are episode-relative known speakers.
    n = len(truth)
    cm = np.bincount(
        (np.arange(n)[:, None] * 36 + truth * 6 + prediction).ravel(), minlength=n * 36
    ).reshape(n, 6, 6)
    tp = np.diagonal(cm, axis1=1, axis2=2)
    denom = cm.sum(axis=1) + cm.sum(axis=2)
    f1 = np.divide(2 * tp, denom, out=np.zeros_like(denom, dtype=float), where=denom != 0).mean(
        axis=1
    )
    known = truth != 5
    return {
        "accuracy": (truth == prediction).mean(axis=1),
        "macro_f1": f1,
        "known_accuracy": ((truth == prediction) & known).sum(axis=1) / known.sum(axis=1),
        "unknown_rejection": ((prediction == 5) & ~known).sum(axis=1) / (~known).sum(axis=1),
        "false_accept_rate": ((prediction != 5) & ~known).sum(axis=1) / (~known).sum(axis=1),
        "false_reject_rate": ((prediction == 5) & known).sum(axis=1) / known.sum(axis=1),
    }


def evaluate(encoder_id, subdir="speaker"):
    import numpy as np

    folder = OUT / subdir
    raw = np.load(folder / f"{encoder_id}.npz", allow_pickle=False)
    embeddings = dict(zip(raw["ids"].tolist(), raw["vectors"], strict=True))
    manifests = read_json(folder / "manifests.json")
    configs = {
        "cosine_prototype": [1],
        "cosine_knn": [1, 3, 5],
        "linear_svm": [0.1, 1.0, 10.0],
        "logistic_regression": [0.1, 1.0, 10.0],
    }
    summaries = []
    episode_rows = []
    thresholds = []
    predictions = []
    for classifier, parameters in configs.items():
        for k in (1, 3, 5):
            dev = [e for e in manifests["vivos_development"] if e["k"] == k]
            candidates = []
            for parameter in parameters:
                scored = [episode_scores(embeddings, e, classifier, parameter) for e in dev]
                accuracy = float(
                    np.mean([np.mean(s[0][s[3] != 5] == s[3][s[3] != 5]) for s in scored])
                )
                candidates.append((accuracy, parameter))
            _, parameter = max(candidates, key=lambda x: (x[0], -float(x[1])))
            validation = [e for e in manifests["vivos_validation"] if e["k"] == k]
            scored = [episode_scores(embeddings, e, classifier, parameter) for e in validation]
            top, best, margin, truth = [np.stack([s[i] for s in scored]) for i in range(4)]
            score_grid = np.unique(
                np.r_[best.min() - 1e-6, np.quantile(best, np.linspace(0, 1, 31))]
            )
            margin_grid = np.unique(np.r_[0.0, np.quantile(margin, np.linspace(0, 0.9, 10))])
            selection = None
            for threshold in score_grid:
                for gate in margin_grid:
                    pred = np.where((best >= threshold) & (margin >= gate), top, 5)
                    metrics = metric_arrays(truth, pred)
                    objective = float(np.mean(metrics["macro_f1"]))
                    key = (
                        objective,
                        float(np.mean(metrics["accuracy"])),
                        -float(threshold),
                        -float(gate),
                    )
                    if selection is None or key > selection[0]:
                        selection = (key, float(threshold), float(gate))
            _, threshold, gate = selection
            frozen = {
                "encoder": encoder_id,
                "classifier": classifier,
                "k": k,
                "parameter": float(parameter),
                "score_threshold": threshold,
                "margin_threshold": gate,
                "selection_split": "vivos_validation",
                "hyperparameter_split": "vivos_development",
                "validation_macro_f1": selection[0][0],
            }
            thresholds.append(frozen)
            for dataset in [key for key in manifests if key.endswith("_test")]:
                episodes = [e for e in manifests[dataset] if e["k"] == k]
                scored = [episode_scores(embeddings, e, classifier, parameter) for e in episodes]
                top, best, margin, truth = [np.stack([s[i] for s in scored]) for i in range(4)]
                pred = np.where((best >= threshold) & (margin >= gate), top, 5)
                metrics = metric_arrays(truth, pred)
                known = truth != 5
                closed = float(np.mean(top[known] == truth[known]))
                row = {
                    "dataset": dataset,
                    **{key: frozen[key] for key in ("encoder", "classifier", "k")},
                    "episodes": len(episodes),
                    "queries": truth.size,
                    "closed_set_accuracy": closed,
                    **{key: float(value.mean()) for key, value in metrics.items()},
                }
                # Cluster bootstrap accuracy by actual source speaker, not repeated queries.
                groups = {}
                for ei, e in enumerate(episodes):
                    for qi, q in enumerate(e["queries"]):
                        groups.setdefault(q["speaker"], []).append(
                            int(pred[ei, qi] == truth[ei, qi])
                        )
                        predictions.append(
                            {
                                "dataset": dataset,
                                "encoder": encoder_id,
                                "classifier": classifier,
                                "k": k,
                                "episode": e["episode"],
                                "query_id": q["id"],
                                "source_speaker": q["speaker"],
                                "known": q["known"],
                                "truth": q["speaker"] if q["known"] else "unknown",
                                "prediction": e["known"][int(pred[ei, qi])]
                                if pred[ei, qi] != 5
                                else "unknown",
                                "score": float(best[ei, qi]),
                                "margin": float(margin[ei, qi]),
                            }
                        )
                totals = np.asarray([(sum(values), len(values)) for values in groups.values()])
                rng = np.random.default_rng(SEED)
                indices = rng.integers(len(totals), size=(1000, len(totals)))
                draws = totals[indices].sum(axis=1)
                ci = np.quantile(draws[:, 0] / draws[:, 1], [0.025, 0.975])
                row.update(
                    accuracy_ci_low=float(ci[0]),
                    accuracy_ci_high=float(ci[1]),
                    ci_method="bootstrap_source_speaker_1000",
                    unique_speakers=len(groups),
                )
                summaries.append(row)
                for i, e in enumerate(episodes):
                    episode_rows.append(
                        {
                            "dataset": dataset,
                            "encoder": encoder_id,
                            "classifier": classifier,
                            "k": k,
                            "episode": e["episode"],
                            **{key: float(value[i]) for key, value in metrics.items()},
                        }
                    )
            log(f"{encoder_id}/{classifier}/K={k} calibrated and evaluated")
    write_json(folder / f"{encoder_id}_frozen_calibration.json", thresholds)
    write_json(folder / f"{encoder_id}_summary.json", summaries)
    write_csv(folder / f"{encoder_id}_summary.csv", summaries)
    write_csv(folder / f"{encoder_id}_episodes.csv", episode_rows)
    write_csv(folder / f"{encoder_id}_predictions.csv", predictions)


def main():
    setup()
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "extract", "evaluate", "all"])
    parser.add_argument("--encoder", choices=["E0", "E1", "E2", "E3", "E4"])
    parser.add_argument("--subdir", choices=["speaker", "speaker_synthetic"], default="speaker")
    args = parser.parse_args()
    if args.command == "prepare":
        make_manifests()
        log("Speaker manifests ready")
    elif args.command == "extract":
        extract(args.encoder, args.subdir)
    elif args.command == "evaluate":
        evaluate(args.encoder, args.subdir)
    else:
        if args.subdir == "speaker":
            make_manifests()
        for encoder in ("E1", "E3", "E2", "E4", "E0"):
            extract(encoder, args.subdir)
            evaluate(encoder, args.subdir)
            gc.collect()
            from experiments.comparative_benchmark.reviews import refresh

            refresh()


if __name__ == "__main__":
    main()
