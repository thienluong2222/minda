"""Paired Vietnamese ASR evaluation with native alignments and no text-generating LLM."""

from __future__ import annotations

import argparse
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
    WEB,
    log,
    read_json,
    rss_mb,
    setup,
    snapshot,
    write_csv,
    write_json,
)

MODELS = {
    "phowhisper_small": "vinai/PhoWhisper-small",
    "phowhisper_medium": "vinai/PhoWhisper-medium",
    "whisper_turbo": "openai/whisper-large-v3-turbo",
    "wav2vec2_vi": "nguyenvulebinh/wav2vec2-base-vietnamese-250h",
    "phowhisper_large": "vinai/PhoWhisper-large",
}


def prepare_synthetic():
    import soundfile as sf

    original = read_json(OUT / "asr/manifest.json")
    original = [r for r in original if not r["split"].startswith("synthetic_")]
    corpus = {
        r["utterance_id"]: r
        for r in map(json.loads, (ROOT / "data/manifests/vivos.jsonl").read_text().splitlines())
    }
    selected = []
    for index, case in enumerate(read_json(OUT / "simulation/manifest.json")):
        if case["split"] == "development":
            continue
        eligible = [
            turn
            for turn in case["turns"]
            if not any(
                other is not turn
                and min(turn["end_sec"], other["end_sec"])
                > max(turn["start_sec"], other["start_sec"]) + 0.001
                for other in case["turns"]
            )
        ]
        turn = eligible[index % len(eligible)]
        wave, sr = sf.read(case["sources"][0]["path"], dtype="float32")
        audio = wave[round(turn["start_sec"] * sr) : round(turn["end_sec"] * sr)]
        key = case["id"] + "_single_turn"
        path = OUT / "asr/audio" / f"{key}.wav"
        sf.write(path, audio, sr, subtype="PCM_16")
        row = {
            "id": key,
            "meeting_id": case["id"],
            "origin_id": turn["origin_id"],
            "speaker_id": turn["speaker"],
            "split": "synthetic_" + case["split"],
            "condition": case["condition"],
            "reference": turn["reference"],
            "duration_sec": len(audio) / sr,
            "audio_path": str(path),
            "audio_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "source_audio_sha256": turn["source_sha256"],
            "evidence_type": "single_non_overlap_turn_from_pyroomacoustics_synthetic_meeting",
        }
        selected.append(row)
        clean_path = ROOT / corpus[turn["origin_id"]]["audio_path"]
        selected.append(
            {
                **row,
                "id": key + "_clean_control",
                "condition": "clean_control",
                "audio_path": str(clean_path),
                "audio_sha256": hashlib.sha256(clean_path.read_bytes()).hexdigest(),
                "evidence_type": "paired_clean_source_control",
            }
        )
    write_json(OUT / "asr/manifest.json", original + selected)
    write_json(
        OUT / "asr/synthetic_protocol.json",
        {
            "validation_meetings": 9,
            "test_meetings": 30,
            "samples_per_meeting": "one_non_overlap_simulated_turn_and_same_utterance_clean_control",
            "selection": "deterministic_turn_index_no_model_outputs_used",
            "labels": "original_human_VIVOS_transcripts",
            "no_LLM": True,
            "test_not_used_for_decoding_or_guard_tuning": True,
        },
    )
    log(f"Synthetic ASR dataset ready: {len(selected)} clips")


def prepare():
    import numpy as np
    import soundfile as sf
    from scipy.signal import fftconvolve

    rows = [
        json.loads(line) for line in (ROOT / "data/manifests/vivos.jsonl").read_text().splitlines()
    ]
    chosen = []
    for split, per_speaker in (("development", 1), ("validation", 1), ("test", 2)):
        speakers = sorted({r["speaker_id"] for r in rows if r["split"] == split})
        if split == "development":
            speakers = speakers[:4]
        rng = np.random.default_rng(SEED + {"development": 0, "validation": 1, "test": 2}[split])
        for speaker in speakers:
            candidates = [
                r
                for r in rows
                if r["speaker_id"] == speaker
                and not r["is_enrollment"]
                and 2 <= r["duration_sec"] <= 8
            ]
            for index in rng.choice(len(candidates), per_speaker, replace=False):
                row = candidates[int(index)]
                chosen.append(row)
    manifest = []
    for index, row in enumerate(chosen):
        wave, sr = sf.read(ROOT / row["audio_path"], dtype="float32")
        assert sr == 16000
        rng = np.random.default_rng(SEED + index)
        conditions = ["clean"]
        # One paired triplet per test speaker; the second utterance remains clean.
        if row["split"] == "test" and not any(
            r["speaker_id"] == row["speaker_id"] and r["condition"] == "moderate" for r in manifest
        ):
            conditions += ["moderate", "stress"]
        for condition in conditions:
            signal = wave.copy()
            if condition != "clean":
                rt60, snr = (0.25, 15.0) if condition == "moderate" else (0.55, 5.0)
                t = np.arange(round(rt60 * 16000)) / 16000
                rir = np.exp(-6.9078 * t / rt60) * rng.normal(0, 0.04, len(t))
                rir[0] = 1.0
                signal = fftconvolve(signal, rir).astype(np.float32)[: len(wave)]
                noise = rng.normal(size=len(signal)).astype(np.float32)
                noise *= np.sqrt(
                    np.mean(signal**2) / (10 ** (snr / 10) * np.mean(noise**2) + 1e-12)
                )
                signal += noise
                if condition == "stress":
                    signal = np.clip(signal, -0.45, 0.45)
            peak = np.max(np.abs(signal))
            if peak > 0.98:
                signal *= 0.98 / peak
            key = f"{row['utterance_id']}_{condition}"
            path = OUT / "asr/audio" / f"{key}.wav"
            path.parent.mkdir(parents=True, exist_ok=True)
            sf.write(path, signal, 16000, subtype="PCM_16")
            manifest.append(
                {
                    "id": key,
                    "origin_id": row["utterance_id"],
                    "speaker_id": row["speaker_id"],
                    "split": row["split"],
                    "condition": condition,
                    "reference": row["text_normalized"],
                    "duration_sec": len(signal) / 16000,
                    "audio_path": str(path),
                    "audio_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "source_audio_sha256": row["audio_sha256"],
                    "evidence_type": "corpus_human_transcript"
                    if condition == "clean"
                    else "controlled_augmentation_of_human_transcribed_audio",
                }
            )
    write_json(OUT / "asr/manifest.json", manifest)
    config = {
        "seed": SEED,
        "primary_metric": "pooled_WER",
        "secondary_metrics": [
            "CER",
            "substitutions",
            "deletions",
            "insertions",
            "failure_rate",
            "RTF",
            "RSS",
        ],
        "normalization": "NFC_lowercase_remove_punctuation_keep_diacritics_same_for_ref_and_hyp",
        "decoder": "production_PhoWhisper_settings_and_quality_guard;greedy_native_CTC_for_wav2vec2;no_external_LM",
        "test_selection": "2_non_enrollment_2_to_8_second_utterances_per_each_of_19_test_speakers;one_augmented_triplet_per_speaker",
        "conditions": {
            "moderate": {"synthetic_rt60_sec": 0.25, "snr_db": 15},
            "stress": {"synthetic_rt60_sec": 0.55, "snr_db": 5, "clipping_limit": 0.45},
        },
        "test_status": "reused_VIVOS_public_test_not_unseen_meeting_domain",
        "sample_counts": {
            split: sum(r["split"] == split for r in manifest)
            for split in ("development", "validation", "test")
        },
    }
    write_json(OUT / "asr/protocol.json", config)
    log(f"ASR dataset ready {config['sample_counts']}")


def make_adapter(name, device="cpu", dtype="float32"):
    from meeting_pipeline.adapters.phowhisper_asr import (
        AsrResult,
        BaseAsrAdapter,
        PhoWhisperAsrAdapter,
    )
    from meeting_pipeline.asr.quality import check_asr_quality
    from meeting_pipeline.config import load_config
    from meeting_pipeline.domain.transcription import TimedWord

    config = load_config(WEB / "configs/default.yaml").asr.model_copy(deep=True)
    model_id = MODELS[name]
    path = snapshot(model_id)
    config.model_id = model_id
    config.model_revision = path.name
    if name != "wav2vec2_vi":
        adapter = PhoWhisperAsrAdapter(config, CACHE)
        if device != "cpu":
            import torch

            pipe = adapter._load_pipeline()
            pipe.model.to(dtype=getattr(torch, dtype)).to(torch.device(device))
            pipe.device = torch.device(device)
        return adapter

    class CTCAdapter(BaseAsrAdapter):
        def __init__(self):
            import torch
            from transformers import AutoModelForCTC, AutoProcessor

            self.processor = AutoProcessor.from_pretrained(path, local_files_only=True)
            self.model = (
                AutoModelForCTC.from_pretrained(path, local_files_only=True)
                .to(dtype=getattr(torch, dtype))
                .to(torch.device(device))
                .eval()
            )

        def transcribe(self, waveform, sample_rate=16000):
            import numpy as np
            import torch

            inputs = self.processor(waveform, sampling_rate=sample_rate, return_tensors="pt")
            inputs = {
                key: value.to(device, dtype=getattr(torch, dtype))
                if value.is_floating_point()
                else value.to(device)
                for key, value in inputs.items()
            }
            with torch.inference_mode():
                logits = self.model(**inputs).logits[0].cpu()
            ids = logits.argmax(-1)
            decoded = self.processor.tokenizer.decode(ids.tolist(), output_word_offsets=True)
            step = self.model.config.inputs_to_logits_ratio / sample_rate
            probabilities = logits.softmax(-1).max(-1).values.numpy()
            words = []
            for word in decoded.word_offsets:
                start, end = int(word["start_offset"]), int(word["end_offset"])
                confidence = float(np.mean(probabilities[start:end])) if end > start else 0.0
                words.append(
                    TimedWord(
                        text=word["word"],
                        start_sec=start * step,
                        end_sec=min(end * step, len(waveform) / sample_rate),
                        confidence=confidence,
                    )
                )
            check = check_asr_quality(decoded.text, words, len(waveform) / sample_rate, config)
            return AsrResult(
                text=decoded.text if check.accepted else "",
                words=words if check.accepted else [],
                status="transcribed" if check.accepted else "unreliable",
                warnings=list(check.issues),
                raw_candidates=[
                    {
                        "text": decoded.text,
                        "native_alignment": "CTC_word_offsets",
                        "confidence_definition": "mean_max_frame_posterior_not_cross_model_calibrated",
                    }
                ],
            )

    return CTCAdapter()


def run(name, split, limit=None, device="cpu", dtype="float32"):
    import soundfile as sf
    import torch

    manifest = read_json(OUT / "asr/manifest.json")
    rows = [r for r in manifest if r["split"] == split]
    if limit:
        rows = rows[:limit]
    group = "asr" if device == "cpu" else "asr_mps" if dtype == "float32" else "asr_mps_float16"
    destination = OUT / group / name
    destination.mkdir(parents=True, exist_ok=True)
    predictions_path = destination / f"{split}_predictions.jsonl"
    completed = {}
    if predictions_path.exists():
        completed = {r["id"]: r for r in map(json.loads, predictions_path.read_text().splitlines())}
    began = time.perf_counter()
    if device == "mps" and not torch.backends.mps.is_available():
        raise RuntimeError(
            "MPS unavailable in this process; run the MPS benchmark outside the restricted sandbox"
        )
    adapter = make_adapter(name, device, dtype)
    # Force lazy weight loading separately from measured per-clip inference.
    if hasattr(adapter, "_load_pipeline"):
        adapter._load_pipeline()
    load_sec = time.perf_counter() - began
    model_path = snapshot(MODELS[name])
    warmup_row = next(r for r in manifest if r["split"] == "development")
    warmup_wave, warmup_sr = sf.read(warmup_row["audio_path"], dtype="float32")
    warmup_start = time.perf_counter()
    adapter.transcribe(warmup_wave, warmup_sr)
    if device == "mps":
        torch.mps.synchronize()
    warmup_sec = time.perf_counter() - warmup_start
    for index, row in enumerate(rows):
        if row["id"] in completed:
            continue
        wave, sr = sf.read(row["audio_path"], dtype="float32")
        torch.manual_seed(SEED + index)
        started = time.perf_counter()
        try:
            result = adapter.transcribe(wave, sr)
            output = result.model_dump()
        except Exception as exc:
            output = {
                "text": "",
                "words": [],
                "status": "failed",
                "warnings": [f"{type(exc).__name__}: {str(exc)[:500]}"],
            }
        elapsed = time.perf_counter() - started
        if device == "mps":
            torch.mps.synchronize()
        elapsed = time.perf_counter() - started
        prediction = {
            **row,
            "model": name,
            "model_id": MODELS[name],
            "revision": model_path.name,
            "device": device,
            "dtype": dtype,
            "result": output,
            "seconds": elapsed,
            "rtf": elapsed / row["duration_sec"],
            "peak_rss_mb": rss_mb(),
            "timing_cache": False,
        }
        with predictions_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(prediction, ensure_ascii=False) + "\n")
        completed[row["id"]] = prediction
        log(
            f"{name}/{split} {index + 1}/{len(rows)} {row['condition']}: {elapsed:.2f}s {output['status']}"
        )
    write_json(
        destination / f"{split}_runtime.json",
        {
            "load_sec": load_sec,
            "warmup_sec": warmup_sec,
            "warmup_split": "development",
            "peak_rss_mb": rss_mb(),
            "model_id": MODELS[name],
            "revision": model_path.name,
            "device": device,
            "dtype": dtype,
            "mps_allocated_mb": torch.mps.current_allocated_memory() / 1e6
            if device == "mps"
            else None,
            "python": sys.executable,
            "cache_used_for_inference": False,
        },
    )
    summarize(name, split, group)


def summarize(name, split, group="asr"):
    import jiwer
    import numpy as np

    from meeting_pipeline.data.vivos import normalize_vietnamese_text

    file = OUT / group / name / f"{split}_predictions.jsonl"
    rows = [json.loads(line) for line in file.read_text().splitlines()]
    summary = []
    for condition in ["all", "simulated_only", *sorted({r["condition"] for r in rows})]:
        selected = [
            r
            for r in rows
            if condition == "all"
            or (condition == "simulated_only" and r["condition"] in ("easy", "moderate", "stress"))
            or r["condition"] == condition
        ]
        if not selected:
            continue
        refs = [normalize_vietnamese_text(r["reference"]) for r in selected]
        hyps = [normalize_vietnamese_text(r["result"]["text"]) for r in selected]
        words = jiwer.process_words(refs, hyps)
        chars = jiwer.process_characters(refs, hyps)
        raw_hyps = [
            normalize_vietnamese_text(
                (r["result"].get("raw_candidates") or [{}])[0].get("text", r["result"]["text"])
            )
            for r in selected
        ]
        raw_wer = jiwer.process_words(refs, raw_hyps).wer
        paired_clean_wer = None
        if condition in ("easy", "moderate", "stress", "simulated_only"):
            keys = {r.get("meeting_id", r["origin_id"]) for r in selected}
            controls = [
                r
                for r in rows
                if r["condition"] in ("clean", "clean_control")
                and r.get("meeting_id", r["origin_id"]) in keys
            ]
            if controls:
                paired_clean_wer = jiwer.wer(
                    [normalize_vietnamese_text(r["reference"]) for r in controls],
                    [normalize_vietnamese_text(r["result"]["text"]) for r in controls],
                )
        per_speaker = {}
        for r, ref, hyp in zip(selected, refs, hyps, strict=True):
            metric = jiwer.process_words(ref, hyp)
            pair = (
                metric.substitutions + metric.deletions + metric.insertions,
                metric.hits + metric.substitutions + metric.deletions,
            )
            per_speaker.setdefault(r["speaker_id"], []).append(pair)
        groups = np.asarray([np.asarray(items).sum(axis=0) for items in per_speaker.values()])
        rng = np.random.default_rng(SEED)
        sampled = groups[rng.integers(len(groups), size=(1000, len(groups)))].sum(axis=1)
        ci = np.quantile(sampled[:, 0] / np.maximum(sampled[:, 1], 1), [0.025, 0.975])
        summary.append(
            {
                "model": name,
                "split": split,
                "condition": condition,
                "samples": len(selected),
                "speakers": len(groups),
                "wer": words.wer,
                "paired_clean_wer": paired_clean_wer,
                "paired_delta_wer": words.wer - paired_clean_wer
                if paired_clean_wer is not None
                else None,
                "first_decode_wer": raw_wer,
                "wer_ci_low": float(ci[0]),
                "wer_ci_high": float(ci[1]),
                "cer": chars.cer,
                "substitutions": words.substitutions,
                "deletions": words.deletions,
                "insertions": words.insertions,
                "reference_words": words.hits + words.substitutions + words.deletions,
                "failure_rate": sum(r["result"]["status"] != "transcribed" for r in selected)
                / len(selected),
                "inference_seconds": sum(r["seconds"] for r in selected),
                "audio_seconds": sum(r["duration_sec"] for r in selected),
                "rtf": sum(r["seconds"] for r in selected)
                / sum(r["duration_sec"] for r in selected),
                "peak_rss_mb": max(r["peak_rss_mb"] for r in selected),
                "ci_method": "bootstrap_source_speaker_1000",
            }
        )
    write_json(file.with_name(f"{split}_summary.json"), summary)
    write_csv(file.with_name(f"{split}_summary.csv"), summary)
    log(f"{name} {split} WER={summary[0]['wer']:.4f} CER={summary[0]['cer']:.4f}")


def main():
    setup()
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "prepare-synthetic", "run", "summarize"])
    parser.add_argument("--model", choices=list(MODELS))
    parser.add_argument(
        "--split",
        choices=["development", "validation", "test", "synthetic_validation", "synthetic_test"],
        default="development",
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--device", choices=["cpu", "mps"], default="cpu")
    parser.add_argument("--dtype", choices=["float32", "float16"], default="float32")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare()
    elif args.command == "prepare-synthetic":
        prepare_synthetic()
    elif args.command == "run":
        run(args.model, args.split, args.limit, args.device, args.dtype)
    else:
        summarize(
            args.model,
            args.split,
            "asr"
            if args.device == "cpu"
            else "asr_mps"
            if args.dtype == "float32"
            else "asr_mps_float16",
        )


if __name__ == "__main__":
    main()
