"""Four two-speaker separators; PIT SI-SDR measured against known acoustic stems."""

from __future__ import annotations

import argparse
import itertools
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.comparative_benchmark.common import (
    OUT,
    log,
    read_json,
    rss_mb,
    setup,
    snapshot,
    write_csv,
    write_json,
)

MODELS = {
    "sepformer_whamr": "speechbrain/sepformer-whamr",
    "sepformer_wham": "speechbrain/sepformer-wham",
    "sepformer_libri2mix": "speechbrain/sepformer-libri2mix",
    "convtasnet": "mpariente/ConvTasNet_WHAM_sepclean",
}


def si_sdr(reference, estimate):
    import numpy as np

    ref = reference.astype(np.float64) - np.mean(reference)
    est = estimate.astype(np.float64) - np.mean(estimate)
    target = np.dot(est, ref) * ref / max(float(np.dot(ref, ref)), 1e-12)
    return float(
        10
        * np.log10((np.dot(target, target) + 1e-12) / (np.dot(est - target, est - target) + 1e-12))
    )


def prepare():
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly

    entries = []
    for case in read_json(OUT / "simulation/manifest.json"):
        if case["split"] == "development" or case["condition"] == "easy":
            continue
        a, b = case["turns"][1:3]
        start = min(a["start_sec"], b["start_sec"])
        end = max(a["end_sec"], b["end_sec"])
        left, right = round(start * 16000), round(end * 16000)
        mix, sr = sf.read(case["sources"][0]["path"], dtype="float32")
        assert sr == 16000
        targets = []
        for turn in (a, b):
            wave, _ = sf.read(case["sources"][0]["clean_stems"][turn["speaker"]], dtype="float32")
            targets.append(resample_poly(wave[left:right], 1, 2).astype(np.float32))
        mixed = resample_poly(mix[left:right], 1, 2).astype(np.float32)
        folder = OUT / "separation/inputs"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{case['id']}.npz"
        np.savez_compressed(path, mixture=mixed, targets=np.stack(targets))
        entries.append(
            {
                "id": case["id"],
                "split": case["split"],
                "condition": case["condition"],
                "path": str(path),
                "duration_sec": len(mixed) / 8000,
                "speaker_ids": [a["speaker"], b["speaker"]],
                "references": [a["reference"], b["reference"]],
            }
        )
    write_json(OUT / "separation/manifest.json", entries)
    write_json(
        OUT / "separation/protocol.json",
        {
            "evidence": "real_pretrained_separator_inference_on_simulated_Vietnamese_two_speaker_audio",
            "sample_rate": 8000,
            "target": "reverberant_acoustic_source_images_at_reference_mic",
            "permutation_invariant": True,
            "baseline": "unseparated_mixture_for_each_target",
            "inactive_in_application_pipeline": True,
            "not_claimed": "improved_application_overlap_transcription",
            "data_limit": "natural_internal_silence_and_reverberant_targets_differ_from_some_training_tasks",
        },
    )


def run(name):
    import numpy as np
    import torch
    from speechbrain.utils.fetching import FetchConfig

    path = snapshot(MODELS[name])
    started = time.perf_counter()
    if name == "convtasnet":
        from asteroid.models import BaseModel

        weights = next(
            (
                path / file
                for file in ("pytorch_model.bin", "model.pth", "model.pt")
                if (path / file).is_file()
            ),
            None,
        )
        if weights is None:
            raise FileNotFoundError(f"No ConvTasNet weights in {path}")
        model = BaseModel.from_pretrained(str(weights)).eval()

        def infer(wave):
            with torch.inference_mode():
                return model(torch.from_numpy(wave).unsqueeze(0))[0].numpy()
    else:
        from speechbrain.inference.separation import SepformerSeparation

        model = SepformerSeparation.from_hparams(
            source=str(path),
            savedir=str(OUT / "runtime" / name),
            run_opts={"device": "cpu"},
            fetch_config=FetchConfig(allow_network=False),
        )

        def infer(wave):
            with torch.inference_mode():
                return (
                    model.separate_batch(torch.from_numpy(wave).unsqueeze(0))[0]
                    .transpose(0, 1)
                    .numpy()
                )

    load_sec = time.perf_counter() - started
    rows = []
    for entry in read_json(OUT / "separation/manifest.json"):
        raw = np.load(entry["path"])
        wave = raw["mixture"]
        targets = raw["targets"]
        started = time.perf_counter()
        estimated = infer(wave)
        elapsed = time.perf_counter() - started
        length = min(estimated.shape[1], targets.shape[1])
        targets = targets[:, :length]
        estimated = estimated[:, :length]
        wave = wave[:length]
        scores = []
        for permutation in itertools.permutations((0, 1)):
            scores.append(
                (
                    np.mean([si_sdr(targets[i], estimated[permutation[i]]) for i in range(2)]),
                    permutation,
                )
            )
        score, permutation = max(scores, key=lambda x: x[0])
        baseline = float(np.mean([si_sdr(target, wave) for target in targets]))
        rows.append(
            {
                "model": name,
                "case": entry["id"],
                "split": entry["split"],
                "condition": entry["condition"],
                "si_sdr_db": float(score),
                "baseline_si_sdr_db": baseline,
                "si_sdr_improvement_db": float(score - baseline),
                "seconds": elapsed,
                "rtf": elapsed / entry["duration_sec"],
                "assignment": list(permutation),
            }
        )
        log(f"{name}/{entry['id']}: SI-SDRi={score - baseline:.2f}dB {elapsed:.2f}s")
    summary = []
    for condition in ("all", "moderate", "stress"):
        selected = [
            r
            for r in rows
            if r["split"] == "test" and (condition == "all" or r["condition"] == condition)
        ]
        summary.append(
            {
                "model": name,
                "condition": condition,
                "cases": len(selected),
                "si_sdr_db": float(np.mean([r["si_sdr_db"] for r in selected])),
                "si_sdr_improvement_db": float(
                    np.mean([r["si_sdr_improvement_db"] for r in selected])
                ),
                "negative_improvement_rate": float(
                    np.mean([r["si_sdr_improvement_db"] < 0 for r in selected])
                ),
                "rtf": float(np.mean([r["rtf"] for r in selected])),
                "load_sec": load_sec,
                "peak_rss_mb": rss_mb(),
            }
        )
    destination = OUT / "separation" / name
    write_json(destination / "summary.json", summary)
    write_csv(destination / "summary.csv", summary)
    write_csv(destination / "per_case.csv", rows)


def main():
    setup()
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "run"])
    parser.add_argument("--model", choices=list(MODELS))
    args = parser.parse_args()
    prepare() if args.command == "prepare" else run(args.model)


if __name__ == "__main__":
    main()
