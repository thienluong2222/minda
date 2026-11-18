"""Check synthetic activity-reference sensitivity before recommending any VAD training."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.comparative_benchmark.common import (
    OUT,
    ROOT,
    read_json,
    setup,
    write_csv,
    write_json,
)


def main():
    import numpy as np
    import soundfile as sf
    from scipy.ndimage import binary_closing, binary_dilation

    from experiments.comparative_benchmark.segmentation import (
        BIN,
        SEG,
        binary_counts,
        metrics,
        reference,
        smooth_mask,
    )

    setup()
    corpus = {
        r["utterance_id"]: r
        for r in map(json.loads, (ROOT / "data/manifests/vivos.jsonl").read_text().splitlines())
    }
    cases = [r for r in read_json(OUT / "simulation/manifest.json") if r["split"] == "test"]
    reference_rows = []
    energy_by_case = {}
    for case in cases:
        centers, extent = reference(case)
        samples = len(centers) * 320
        stems = {s: np.zeros(samples, dtype=np.float32) for s in case["speakers"]}
        for turn in case["turns"]:
            wave, sr = sf.read(ROOT / corpus[turn["origin_id"]]["audio_path"], dtype="float32")
            start = round(turn["start_sec"] * sr)
            end = min(samples, start + len(wave))
            stems[turn["speaker"]][start:end] += wave[: end - start]
        count = np.zeros(len(centers), dtype=int)
        for wave in stems.values():
            rms = np.sqrt(np.mean(wave.reshape(-1, 320) ** 2, axis=1))
            positive = rms[rms > 0]
            threshold = (
                max(float(np.percentile(positive, 95)) * 0.025, 1e-5) if len(positive) else 1e-5
            )
            active = rms > threshold
            active = binary_dilation(
                binary_closing(active, structure=np.ones(3)), structure=np.ones(3)
            )
            count += active.astype(int)
        energy_by_case[case["id"]] = count
        reference_rows.append(
            {
                "case": case["id"],
                "condition": case["condition"],
                "extent_speech_seconds": float(np.count_nonzero(extent > 0) * BIN),
                "dry_energy_speech_seconds": float(np.count_nonzero(count > 0) * BIN),
                "extent_overlap_seconds": float(np.count_nonzero(extent >= 2) * BIN),
                "dry_energy_overlap_seconds": float(np.count_nonzero(count >= 2) * BIN),
                "speech_label_disagreement_rate": float(np.mean((extent > 0) != (count > 0))),
            }
        )
    comparisons = []
    for name in [*SEG, "silero", "crdnn", "fsmn"]:
        destination = OUT / "segmentation" / name
        if not (destination / "summary.json").exists():
            continue
        threshold = read_json(destination / "calibration.json")["threshold"]
        pooled_vad = {k: 0 for k in ("tp", "fp", "fn", "tn")}
        pooled_overlap = pooled_vad.copy()
        for case in cases:
            raw = np.load(destination / f"{case['id']}.npz")
            truth = energy_by_case[case["id"]]
            pred = smooth_mask(raw["activity"], case["duration_sec"], threshold)
            scores = binary_counts(truth > 0, pred)
            for key in scores:
                pooled_vad[key] += scores[key]
            if name in SEG:
                scores = binary_counts(truth >= 2, np.floor(raw["count"] + 0.5) >= 2)
                for key in scores:
                    pooled_overlap[key] += scores[key]
        original = read_json(destination / "summary.json")
        comparisons.append(
            {
                "model": name,
                "task": "vad",
                "extent_reference_f1": next(
                    r["f1"] for r in original if r["task"] == "vad" and r["condition"] == "all"
                ),
                "energy_reference_f1": metrics(pooled_vad)["f1"],
                "reference_status": "diagnostic_not_human_frame_labels",
            }
        )
        if name in SEG:
            comparisons.append(
                {
                    "model": name,
                    "task": "overlap",
                    "extent_reference_f1": next(
                        r["f1"]
                        for r in original
                        if r["task"] == "overlap" and r["condition"] == "all"
                    ),
                    "energy_reference_f1": metrics(pooled_overlap)["f1"],
                    "reference_status": "diagnostic_not_human_frame_labels",
                }
            )
    write_json(
        OUT / "reference_diagnostics.json",
        {
            "method": "dry_source_RMS_20ms; threshold=2.5%_95th_percentile_nonzero_RMS; close_60ms; pad_20ms",
            "initial_extent_results_preserved": True,
            "not_a_replacement_human_gold": True,
            "cases": reference_rows,
            "model_sensitivity": comparisons,
        },
    )
    write_csv(OUT / "reference_diagnostics.csv", comparisons)
    # One inspectable plot connects the metric sensitivity to the actual source clock.
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    case = next(c for c in cases if c["id"].startswith("test_005_"))
    centers, extent = reference(case)
    fig, axes = plt.subplots(2, 1, figsize=(12, 5), sharex=True)
    axes[0].step(centers, extent, label="Utterance extent", where="mid", alpha=0.8)
    axes[0].step(
        centers, energy_by_case[case["id"]], label="Dry-energy diagnostic", where="mid", alpha=0.8
    )
    axes[0].set_ylabel("Reference count")
    axes[0].legend(loc="upper right")
    for name in SEG:
        raw = np.load(OUT / "segmentation" / name / f"{case['id']}.npz")
        axes[1].plot(centers, raw["count"], label=name, alpha=0.8)
    axes[1].set_ylabel("Predicted count")
    axes[1].set_xlabel("Canonical meeting time (seconds)")
    axes[1].legend(ncol=2)
    fig.suptitle("Synthetic overlap: reference sensitivity before fine-tuning")
    fig.tight_layout()
    fig.savefig(OUT / "reference_diagnostic.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    main()
