"""Read-only diagnostic summary for a measured user-audio run, without reference WER."""

import argparse
import json
from collections import Counter
from pathlib import Path


def intervals(rows):
    merged = []
    for start, end in sorted((float(r["start_sec"]), float(r["end_sec"])) for r in rows):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def duration(rows):
    return sum(end - start for start, end in intervals(rows))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    base = args.output
    run = Path(json.loads((base / "run_path.json").read_text())["run"])
    rows = json.loads((run / "timeline.json").read_text())["segments"]
    activity = json.loads((run / "activity_regions.json").read_text())["segments"]
    timings = json.loads((base / "asr_timings.json").read_text())
    bad = [r for r in rows if r.get("asr_status") != "transcribed" or not r.get("text", "").strip()]
    recognized = [
        r for r in rows if r.get("asr_status") == "transcribed" and r.get("text", "").strip()
    ]
    result = {
        "scope": "structural diagnostics on a user recording, no corrected reference transcript",
        "run": str(run),
        "segments": len(rows),
        "words": sum(len(r.get("text", "").split()) for r in rows),
        "asr_status_counts": dict(Counter(r.get("asr_status") for r in rows)),
        "detected_speech_sec": duration(activity),
        "recognized_interval_sec": duration(recognized),
        "unrecognized_interval_sec": duration(bad),
        "speaker_labels_are_predictions": True,
        "predicted_speaker_labels": sorted({str(r.get("speaker_label")) for r in rows}),
        "asr_calls": len(timings),
        "asr_inference_sec": sum(r["wall_sec"] for r in timings),
        "cpu_fallback_calls": sum("asr_cpu_fallback" in r["warnings"] for r in timings),
        "wall_sec_for_fallback_clips": sum(
            r["wall_sec"] for r in timings if "asr_cpu_fallback" in r["warnings"]
        ),
        "unrecognized_spans": [
            {k: r.get(k) for k in ["segment_id", "start_sec", "end_sec", "asr_status", "warnings"]}
            for r in bad
        ],
        "wer": None,
        "semantic_accuracy_verified": False,
    }
    path = run / "minutes/model_report.json"
    if path.is_file():
        report = json.loads(path.read_text())
        checks = json.loads(path.with_name("verification.json").read_text())["checks"]
        result["minutes"] = {
            "units": report["unit_count"],
            "nodes": report["node_count"],
            "edges": report["edge_count"],
            "topics": report["cluster_count"],
            "wall_sec": report["wall_sec"],
            "llm_calls": len(report["calls"]),
            "llm_response_cache_hits": sum(c.get("cache_hit", False) for c in report["calls"]),
            "output_tokens": sum(c.get("generation_tokens", 0) for c in report["calls"]),
            "coverage": report["coverage"],
            "writer_actions": dict(Counter(c["action"] for c in checks)),
        }
    (base / "diagnostics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(
        json.dumps(
            {k: v for k, v in result.items() if k not in ["unrecognized_spans", "minutes"]},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
