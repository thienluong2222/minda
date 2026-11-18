"""Paired source-speaker bootstrap; repeated episodes are not independent samples."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.comparative_benchmark.common import OUT, SEED, setup, write_csv, write_json


def bootstrap_delta(groups, draws=2000):
    import numpy as np

    values = np.asarray(groups, dtype=float)
    rng = np.random.default_rng(SEED)
    sampled = values[rng.integers(len(values), size=(draws, len(values)))].sum(axis=1)
    deltas = (sampled[:, 0] - sampled[:, 1]) / np.maximum(sampled[:, 2], 1)
    lower, upper = np.quantile(deltas, [0.025, 0.975])
    totals = values.sum(axis=0)
    return {
        "delta": float((totals[0] - totals[1]) / totals[2]),
        "ci_low": float(lower),
        "ci_high": float(upper),
        "source_speakers": len(values),
        "bootstrap_draws": draws,
        "method": "paired_cluster_bootstrap_actual_source_speaker",
        "scope": "conditional_on_frozen_simulated_corpus",
    }


def asr_statistics():
    import jiwer

    from meeting_pipeline.data.vivos import normalize_vietnamese_text

    root = OUT / "asr_mps_float16"
    baseline_file = root / "phowhisper_medium/synthetic_test_predictions.jsonl"
    if not baseline_file.exists():
        return []
    baseline = {
        r["id"]: r
        for r in map(json.loads, baseline_file.read_text().splitlines())
        if r["condition"] in ("easy", "moderate", "stress")
    }
    results = []
    for file in root.glob("*/synthetic_test_predictions.jsonl"):
        rows = {
            r["id"]: r
            for r in map(json.loads, file.read_text().splitlines())
            if r["condition"] in ("easy", "moderate", "stress")
        }
        if set(rows) != set(baseline):
            continue
        groups = {}
        for key, row in rows.items():
            base = baseline[key]
            if row["audio_sha256"] != base["audio_sha256"]:
                raise ValueError("Unpaired ASR audio")
            reference = normalize_vietnamese_text(row["reference"])
            candidate = jiwer.process_words(
                reference, normalize_vietnamese_text(row["result"]["text"])
            )
            control = jiwer.process_words(
                reference, normalize_vietnamese_text(base["result"]["text"])
            )
            value = groups.setdefault(row["speaker_id"], [0, 0, 0])
            value[0] += candidate.substitutions + candidate.deletions + candidate.insertions
            value[1] += control.substitutions + control.deletions + control.insertions
            value[2] += candidate.hits + candidate.substitutions + candidate.deletions
        result = bootstrap_delta(list(groups.values()))
        result.update(
            model=file.parent.name,
            baseline="phowhisper_medium",
            metric="WER_candidate_minus_baseline;negative_is_better",
            comparison="better"
            if result["ci_high"] < 0
            else "worse"
            if result["ci_low"] > 0
            else "unresolved",
        )
        results.append(result)
    return results


def speaker_statistics():
    root = OUT / "speaker_synthetic"

    def load(encoder):
        with (root / f"{encoder}_predictions.csv").open() as handle:
            return {
                (r["dataset"], r["episode"], r["query_id"]): r
                for r in csv.DictReader(handle)
                if r["k"] == "3" and r["classifier"] == "cosine_prototype"
            }

    baseline = load("E1")
    results = []
    for encoder in ("E1", "E2", "E3", "E4", "E0"):
        candidate = load(encoder)
        assert set(candidate) == set(baseline)
        for condition in ("easy", "moderate", "stress"):
            groups = {}
            for key, row in candidate.items():
                if key[0] != f"sim_{condition}_test":
                    continue
                base = baseline[key]
                value = groups.setdefault(row["source_speaker"], [0, 0, 0])
                value[0] += row["prediction"] == row["truth"]
                value[1] += base["prediction"] == base["truth"]
                value[2] += 1
            result = bootstrap_delta(list(groups.values()))
            result.update(
                encoder=encoder,
                baseline="E1_ECAPA",
                condition=condition,
                k=3,
                classifier="cosine_prototype",
                metric="accuracy_candidate_minus_baseline;positive_is_better",
                comparison="better"
                if result["ci_low"] > 0
                else "worse"
                if result["ci_high"] < 0
                else "unresolved",
            )
            results.append(result)
    return results


def main():
    setup()
    asr = asr_statistics()
    speakers = speaker_statistics()
    write_json(OUT / "paired_comparisons.json", {"ASR": asr, "speaker": speakers})
    write_csv(OUT / "paired_ASR_comparisons.csv", asr)
    write_csv(OUT / "paired_speaker_comparisons.csv", speakers)


if __name__ == "__main__":
    main()
