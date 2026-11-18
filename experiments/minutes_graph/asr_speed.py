"""Compare ASR runtimes on the existing labeled clips, including word timing diagnostics."""

import argparse
import gc
import json
import time
from pathlib import Path


def main():
    import jiwer
    import soundfile as sf
    import torch

    from meeting_pipeline.adapters.phowhisper_asr import PhoWhisperAsrAdapter
    from meeting_pipeline.config import load_config
    from meeting_pipeline.data.vivos import normalize_vietnamese_text

    parser = argparse.ArgumentParser()
    parser.add_argument("--runtimes", nargs="+", default=["mps", "mlx"])
    parser.add_argument("--split", default="validation", choices=["validation", "test"])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--label", default="")
    args = parser.parse_args()
    torch.set_num_threads(2)
    source = (
        Path("reports/comparative_benchmark/20261104/asr/phowhisper_medium")
        / f"synthetic_{args.split}_predictions.jsonl"
    )
    if args.split == "test":
        source = Path(
            "reports/comparative_benchmark/20261104/asr_mps_float16/phowhisper_medium/synthetic_test_predictions.jsonl"
        )
    clips = [json.loads(line) for line in source.read_text().splitlines()][: args.limit]
    out = Path("reports/pipeline_speed/20261109/asr")
    out.mkdir(parents=True, exist_ok=True)
    for runtime in args.runtimes:
        cfg = load_config(Path("web_app/configs/default.yaml"))
        cfg.asr.runtime = runtime
        adapter = PhoWhisperAsrAdapter(cfg.asr, Path("data/model_cache"))
        rows = []
        label = args.label or runtime
        for i, clip in enumerate(clips):
            audio, sr = sf.read(clip["audio_path"], dtype="float32")
            started = time.perf_counter()
            result = adapter.transcribe(audio, sr)
            if runtime == "mps":
                torch.mps.synchronize()
            seconds = time.perf_counter() - started
            row = {
                "id": clip["id"],
                "reference": normalize_vietnamese_text(clip["reference"]),
                "hypothesis": normalize_vietnamese_text(result.text),
                "status": result.status,
                "seconds": seconds,
                "duration_sec": len(audio) / sr,
                "nonpositive_words": sum(w.end_sec <= w.start_sec for w in result.words),
                "words": [w.model_dump() for w in result.words],
                "warnings": result.warnings,
                "errors": [c["error"] for c in result.raw_candidates if "error" in c],
            }
            rows.append(row)
            (out / f"{label}_{args.split}_predictions.json").write_text(
                json.dumps(rows, ensure_ascii=False)
            )
            print(f"{runtime} {i + 1}/{len(clips)} {seconds:.2f}s {result.status}", flush=True)
        refs = " ".join(r["reference"] for r in rows)
        hyps = " ".join(r["hypothesis"] for r in rows)
        summary = {
            "runtime": runtime,
            "split": args.split,
            "samples": len(rows),
            "seconds_including_load": sum(r["seconds"] for r in rows),
            "audio_seconds": sum(r["duration_sec"] for r in rows),
            "wer": jiwer.wer(refs, hyps),
            "cer": jiwer.cer(refs, hyps),
            "failures": sum(r["status"] != "transcribed" for r in rows),
            "nonpositive_words": sum(r["nonpositive_words"] for r in rows),
        }
        (out / f"{label}_{args.split}_summary.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary), flush=True)
        if runtime == "mlx" and adapter._pipeline:
            adapter._pipeline.close()
        del adapter
        gc.collect()
        torch.mps.empty_cache()


if __name__ == "__main__":
    main()
