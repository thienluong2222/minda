"""VAD and local overlap/count screening on the exact same simulated recordings."""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path
from types import SimpleNamespace

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

BIN = 0.02
SEG = {
    "pyannote3": "pyannote/segmentation-3.0",
    "diarizen_base": "BUT-FIT/diarizen-wavlm-base-s80-md",
    "diarizen_large": "BUT-FIT/diarizen-wavlm-large-s80-md",
    "diarizen_v2": "BUT-FIT/diarizen-wavlm-large-s80-md-v2",
}


def binary_counts(truth, prediction):
    import numpy as np

    return {
        "tp": int(np.count_nonzero(truth & prediction)),
        "fp": int(np.count_nonzero(~truth & prediction)),
        "fn": int(np.count_nonzero(truth & ~prediction)),
        "tn": int(np.count_nonzero(~truth & ~prediction)),
    }


def metrics(counts):
    tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
    return {
        **counts,
        "precision": tp / max(tp + fp, 1),
        "recall": tp / max(tp + fn, 1),
        "f1": 2 * tp / max(2 * tp + fp + fn, 1),
        "miss_rate": fn / max(tp + fn, 1),
        "false_alarm_rate": fp / max(fp + counts["tn"], 1),
    }


def reference(case):
    import numpy as np

    centers = (np.arange(math.ceil(case["duration_sec"] / BIN)) + 0.5) * BIN
    count = np.zeros(len(centers), dtype=np.int32)
    for turn in case["turns"]:
        count += (centers >= turn["start_sec"]) & (centers < turn["end_sec"])
    return centers, count


def smooth_mask(curve, duration, threshold):
    import numpy as np

    from meeting_pipeline.pipeline.stages.shared_segmentation import extract_pyannote_vad_intervals

    intervals = extract_pyannote_vad_intervals(
        curve,
        bin_sec=BIN,
        threshold=threshold,
        min_speech_ms=250,
        merge_gap_ms=400,
        speech_pad_ms=250,
        meeting_duration_sec=duration,
    )
    centers = (np.arange(len(curve)) + 0.5) * BIN
    mask = np.zeros(len(curve), dtype=bool)
    for a, b in intervals:
        mask |= (centers >= a) & (centers < b)
    return mask


def load_segmentation(name):
    import torch
    from pyannote.audio import Inference, Model
    from pyannote.audio.core.task import Problem, Resolution, Specifications

    sys.path.insert(0, str(OUT / "runtime/DiariZen"))
    path = snapshot(SEG[name])
    if name == "pyannote3":
        with torch.serialization.safe_globals(
            [torch.torch_version.TorchVersion, Problem, Resolution, Specifications]
        ):
            model = Model.from_pretrained(str(path / "pytorch_model.bin"), map_location="cpu")
    else:
        import tomllib

        import numpy as np
        from diarizen.models.module.conformer import ConformerEncoder
        from diarizen.models.module.wav2vec2.model import wav2vec2_model
        from diarizen.models.module.wavlm_config import get_config
        from pyannote.audio.utils.powerset import Powerset
        from torch import nn

        cfg = tomllib.loads((path / "config.toml").read_text())
        args = cfg["model"]["args"]
        state = torch.load(path / "pytorch_model.bin", map_location="cpu", weights_only=True)

        # Use the author's native components and exact forward path. The hub
        # contains a plain state_dict, not a Lightning checkpoint. This adapter
        # avoids replacing the application's installed pyannote package.
        class LocalEEND(nn.Module):
            def __init__(self):
                super().__init__()
                self.wavlm_model = wav2vec2_model(**get_config(args["wavlm_src"]))
                self.weight_sum = nn.Linear(args["wavlm_layer_num"], 1, bias=False)
                self.proj = nn.Linear(args["wavlm_feat_dim"], args["attention_in"])
                self.lnorm = nn.LayerNorm(args["attention_in"])
                self.conformer = ConformerEncoder(
                    attention_in=args["attention_in"],
                    ffn_hidden=args["ffn_hidden"],
                    num_head=args["num_head"],
                    num_layer=args["num_layer"],
                    kernel_size=args.get("kernel_size", 31),
                    dropout=args["dropout"],
                    use_posi=args["use_posi"],
                    output_activate_function=args["output_activate_function"],
                )
                self.classifier = nn.Linear(
                    args["attention_in"], state["classifier.weight"].shape[0]
                )

            def forward(self, wave):
                features, _ = self.wavlm_model.extract_features(wave)
                combined = self.weight_sum(torch.stack(features, dim=-1)).squeeze(-1)
                return self.classifier(self.conformer(self.lnorm(self.proj(combined))))

        model = LocalEEND().eval()
        model.load_state_dict(state, strict=True)
        duration = float(args["chunk_size"])
        step = duration * 0.25
        speakers = args.get("max_speakers_per_chunk", 4)
        max_active = args.get("max_speakers_per_frame", 2)
        powerset = Powerset(speakers, max_active)
        if powerset.num_powerset_classes != state["classifier.weight"].shape[0]:
            raise ValueError("DiariZen powerset specification does not match downloaded weights")

        def infer(document):
            wave = document["waveform"][0]
            window = round(duration * 16000)
            hop = round(step * 16000)
            starts = list(range(0, max(0, len(wave) - window + 1), hop))
            if not starts:
                starts = [0]
            elif starts[-1] + window < len(wave):
                starts.append(starts[-1] + hop)
            data = []
            with torch.inference_mode():
                for begin in starts:
                    segment = wave[begin : begin + window]
                    segment = torch.nn.functional.pad(
                        segment, (0, window - len(segment))
                    ).unsqueeze(0)
                    logits = model(segment)
                    data.append(powerset.to_multilabel(logits, soft=False)[0].numpy())
            return SimpleNamespace(
                data=np.stack(data), sliding_window=SimpleNamespace(duration=duration, step=step)
            )

        return infer, duration
    model.eval()
    duration = float(model.specifications.duration)
    infer = Inference(
        model, duration=duration, step=duration * 0.25, batch_size=1, device=torch.device("cpu")
    )
    return infer, duration


def aggregate_segmentation(raw, duration):
    import numpy as np

    from meeting_pipeline.pipeline.stages.shared_segmentation import compute_pyannote_activity_curve

    data = np.asarray(raw.data, dtype=np.float32)
    chunk_duration = float(raw.sliding_window.duration)
    step = float(raw.sliding_window.step)
    result = SimpleNamespace(data=data, sliding_window=raw.sliding_window)
    activity = compute_pyannote_activity_curve(result, duration, bin_sec=BIN)
    count = np.zeros(len(activity), dtype=np.float64)
    weight = np.zeros(len(activity), dtype=np.float64)
    centers = (np.arange(len(activity)) + 0.5) * BIN
    frame_centers = (np.arange(data.shape[1]) + 0.5) * chunk_duration / data.shape[1]
    for index, chunk in enumerate(data):
        begin = index * step
        mask = (centers >= begin) & (centers < begin + chunk_duration)
        local = centers[mask] - begin
        taper = np.clip(np.minimum(local, chunk_duration - local) / 1.25, 0.1, 1.0)
        count[mask] += np.interp(local, frame_centers, chunk.sum(axis=1)) * taper
        weight[mask] += taper
    count = np.divide(count, weight, out=np.zeros_like(count), where=weight > 0)
    return activity, count


def generate_curves(name, smoke=False):
    import numpy as np
    import soundfile as sf
    import torch

    cases = read_json(OUT / "simulation/manifest.json")
    if smoke:
        cases = cases[:1]
    destination = OUT / "segmentation" / name
    destination.mkdir(parents=True, exist_ok=True)
    runtime = []
    started = time.perf_counter()
    if name in SEG:
        model, _ = load_segmentation(name)
    elif name == "silero":
        from silero_vad import load_silero_vad

        model = load_silero_vad()
    elif name == "crdnn":
        from speechbrain.inference.VAD import VAD
        from speechbrain.utils.fetching import FetchConfig

        path = snapshot("speechbrain/vad-crdnn-libriparty")
        model = VAD.from_hparams(
            source=str(path),
            savedir=str(OUT / "runtime/crdnn"),
            run_opts={"device": "cpu"},
            fetch_config=FetchConfig(allow_network=False),
        )
    elif name == "fsmn":
        from funasr import AutoModel

        path = snapshot("funasr/fsmn-vad")
        model = AutoModel(
            model=str(path),
            device="cpu",
            disable_update=True,
            hub="hf",
            frontend_conf={"cmvn_file": str(path / "am.mvn")},
            ncpu=4,
        )
    else:
        raise ValueError(name)
    load_sec = time.perf_counter() - started
    for case in cases:
        path = destination / f"{case['id']}.npz"
        if path.exists() and not smoke:
            continue
        wave, sr = sf.read(case["sources"][0]["path"], dtype="float32")
        assert sr == 16000
        n = math.ceil(case["duration_sec"] / BIN)
        centers = (np.arange(n) + 0.5) * BIN
        begin = time.perf_counter()
        with torch.inference_mode():
            if name in SEG:
                raw = model({"waveform": torch.from_numpy(wave).unsqueeze(0), "sample_rate": 16000})
                curve, count = aggregate_segmentation(raw, case["duration_sec"])
            elif name == "silero":
                model.reset_states()
                prob = []
                for i in range(0, len(wave), 512):
                    chunk = torch.from_numpy(
                        np.pad(wave[i : i + 512], (0, max(0, 512 - len(wave[i : i + 512]))))
                    )
                    prob.append(float(model(chunk, 16000).item()))
                curve = np.interp(centers, (np.arange(len(prob)) + 0.5) * 512 / 16000, prob).astype(
                    np.float32
                )
                count = curve
            elif name == "crdnn":
                probability = (
                    model.get_speech_prob_chunk(torch.from_numpy(wave).unsqueeze(0))
                    .reshape(-1)
                    .numpy()
                )
                curve = np.interp(
                    centers, np.linspace(0, len(wave) / 16000, len(probability)), probability
                ).astype(np.float32)
                count = curve
            else:
                output = model.generate(input=wave, cache={}, is_final=True, disable_pbar=True)
                curve = np.zeros(n, dtype=np.float32)
                for a, b in output[0].get("value", []):
                    curve[(centers >= a / 1000) & (centers < b / 1000)] = 1.0
                count = curve
        elapsed = time.perf_counter() - begin
        np.savez_compressed(
            path, activity=curve, count=count, seconds=elapsed, duration=case["duration_sec"]
        )
        runtime.append(
            {
                "case": case["id"],
                "seconds": elapsed,
                "duration_sec": case["duration_sec"],
                "rtf": elapsed / case["duration_sec"],
            }
        )
        log(f"{name} {case['id']} {elapsed:.2f}s")
    write_json(
        destination / ("smoke_runtime.json" if smoke else "runtime.json"),
        {
            "model": name,
            "load_sec": load_sec,
            "peak_rss_mb": rss_mb(),
            "sources_per_case": 1,
            "source_policy": "fixed_source_1_for_component_isolation",
            "timings": runtime,
            "fsmn_note": "native_endpointing_followed_by_shared_postprocessing"
            if name == "fsmn"
            else None,
        },
    )
    return cases


def evaluate(name):
    import numpy as np

    cases = read_json(OUT / "simulation/manifest.json")
    destination = OUT / "segmentation" / name

    def scored(case, threshold):
        raw = np.load(destination / f"{case['id']}.npz")
        _, truth = reference(case)
        prediction = smooth_mask(raw["activity"], case["duration_sec"], threshold)
        return binary_counts(truth > 0, prediction)

    validation = [c for c in cases if c["split"] == "validation"]
    candidates = []
    for threshold in (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8):
        records = [scored(c, threshold) for c in validation]
        totals = {key: sum(r[key] for r in records) for key in ("tp", "fp", "fn", "tn")}
        candidates.append((metrics(totals)["f1"], -abs(threshold - 0.5), threshold))
    threshold = max(candidates)[2]
    write_json(
        destination / "calibration.json",
        {
            "threshold": threshold,
            "selected_on": "validation",
            "candidates": [{"f1": r[0], "threshold": r[2]} for r in candidates],
            "shared_postprocessing": {
                "min_speech_ms": 250,
                "merge_gap_ms": 400,
                "speech_pad_ms": 250,
            },
            "source_reference": "source_utterance_extents_proxy",
        },
    )
    results = []
    per_case = []
    for condition in ("all", "easy", "moderate", "stress"):
        selected = [
            c
            for c in cases
            if c["split"] == "test" and (condition == "all" or c["condition"] == condition)
        ]
        scores = [scored(c, threshold) for c in selected]
        totals = {key: sum(r[key] for r in scores) for key in ("tp", "fp", "fn", "tn")}
        row = {
            "task": "vad",
            "model": name,
            "condition": condition,
            "cases": len(selected),
            "threshold": threshold,
            **metrics(totals),
        }
        results.append(row)
        if name in SEG:
            overlap = []
            count_errors = []
            for c in selected:
                raw = np.load(destination / f"{c['id']}.npz")
                _, truth = reference(c)
                predicted = np.floor(raw["count"] + 0.5).astype(int)
                overlap.append(binary_counts(truth >= 2, predicted >= 2))
                count_errors.extend(
                    np.abs(np.minimum(truth, 2) - np.minimum(predicted, 2)).tolist()
                )
            pooled = {key: sum(r[key] for r in overlap) for key in ("tp", "fp", "fn", "tn")}
            results.append(
                {
                    "task": "overlap",
                    "model": name,
                    "condition": condition,
                    "cases": len(selected),
                    "count_mae": float(np.mean(count_errors)),
                    **metrics(pooled),
                }
            )
        for case, score in zip(selected, scores, strict=True):
            if condition == "all":
                per_case.append(
                    {
                        "case": case["id"],
                        "model": name,
                        "condition": case["condition"],
                        **metrics(score),
                    }
                )
    write_json(destination / "summary.json", results)
    write_csv(destination / "summary.csv", results)
    write_csv(destination / "per_case.csv", per_case)
    log(f"{name} VAD F1={results[0]['f1']:.4f}")


def main():
    setup()
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["run", "evaluate", "smoke"])
    parser.add_argument("--model", choices=[*SEG, "silero", "crdnn", "fsmn"], required=True)
    args = parser.parse_args()
    if args.command in ("run", "smoke"):
        generate_curves(args.model, args.command == "smoke")
    if args.command in ("run", "evaluate"):
        evaluate(args.model)


if __name__ == "__main__":
    main()
