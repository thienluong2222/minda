"""Post-hoc verification ROC/EER from frozen embeddings; never tunes deployment thresholds."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.comparative_benchmark.common import OUT, read_json, setup, write_csv, write_json


def main():
    import numpy as np
    from sklearn.metrics import roc_auc_score, roc_curve

    setup()
    manifest = read_json(OUT / "speaker_synthetic/manifests.json")
    results = []
    for encoder in ("E1", "E2", "E3", "E4", "E0"):
        raw = np.load(OUT / f"speaker_synthetic/{encoder}.npz", allow_pickle=False)
        embeddings = dict(zip(raw["ids"].tolist(), raw["vectors"], strict=True))
        for condition in ("easy", "moderate", "stress"):
            truth = []
            scores = []
            for episode in [e for e in manifest[f"sim_{condition}_test"] if e["k"] == 3]:
                speakers = episode["known"]
                centroids = np.stack(
                    [
                        np.mean([embeddings[i] for i in episode["support"][s]], axis=0)
                        for s in speakers
                    ]
                )
                centroids /= np.maximum(np.linalg.norm(centroids, axis=1, keepdims=True), 1e-12)
                queries = np.stack([embeddings[q["id"]] for q in episode["queries"]])
                similarities = queries @ centroids.T
                for index, q in enumerate(episode["queries"]):
                    truth.extend(
                        [int(q["known"] and speaker == q["speaker"]) for speaker in speakers]
                    )
                    scores.extend(similarities[index].tolist())
            fpr, tpr, _thresholds = roc_curve(truth, scores)
            fnr = 1 - tpr
            index = int(np.argmin(np.abs(fpr - fnr)))
            results.append(
                {
                    "encoder": encoder,
                    "condition": condition,
                    "k": 3,
                    "pairs": len(scores),
                    "genuine_pairs": sum(truth),
                    "eer": float((fpr[index] + fnr[index]) / 2),
                    "roc_auc": float(roc_auc_score(truth, scores)),
                    "threshold_is_diagnostic_only": True,
                    "threshold_not_exported_to_pipeline": True,
                }
            )
    write_json(OUT / "speaker_verification.json", results)
    write_csv(OUT / "speaker_verification.csv", results)


if __name__ == "__main__":
    main()
