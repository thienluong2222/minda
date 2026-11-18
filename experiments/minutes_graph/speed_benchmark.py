"""Uncached real-model speed/coverage probe; never updates live meetings."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from meeting_pipeline.minutes.evidence_retrieval import IndexedTurn
from meeting_pipeline.minutes.graph_inputs import make_graph_units
from meeting_pipeline.minutes.graph_pipeline import generate_graph_minutes, save_json
from meeting_pipeline.minutes.model_runtime import ModelSession, load_model_settings

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--input", choices=["asr", "reference"], default="asr")
    parser.add_argument("--legacy-contract", action="store_true")
    parser.add_argument("--information-budget", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--prefix-cache", type=int, default=3)
    parser.add_argument("--prefill", type=int, default=1024)
    args = parser.parse_args()
    if args.input == "asr":
        source = (
            ROOT
            / "data/meetings/test-c-enroll/runs/3e27f5fa-08d8-443d-a8d3-c44ef62b1479/timeline.json"
        )
        rows = json.loads(source.read_text())["segments"]
    else:
        source = (
            ROOT / "data/generated/fpt_tts_pilot_20261003/meeting_audio/reference_segments.json"
        )
        rows = json.loads(source.read_text())
    turns = [
        IndexedTurn(
            turn_id=r.get("turn_id", r["segment_id"]),
            speaker_label=r.get("speaker_label", r.get("reference_speaker_id", "")),
            speaker_id=r.get("speaker_id"),
            start_sec=r["start_sec"],
            end_sec=r["end_sec"],
            text=r.get("text", r.get("reference_text", "")),
            tokens=[],
            source_id="primary",
            clip_path=None,
            asr_status=r.get("asr_status", "transcribed"),
            needs_review=r.get("needs_review", False),
            confidence=None,
        )
        for r in rows
    ]
    units, excluded = make_graph_units(turns)
    settings = load_model_settings().model_copy(
        update={
            "response_cache": False,
            "compact_graph_output": not args.legacy_contract,
            "extraction_batch_size": 6 if args.legacy_contract else 12,
            "information_budget_per_topic": args.information_budget,
            "inference_batch_size": args.batch_size,
            "prefix_cache_entries": args.prefix_cache,
            "prefill_step_size": args.prefill,
        }
    )
    args.output.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    print(f"START units={len(units)} compact={settings.compact_graph_output}", flush=True)
    with ModelSession(args.output / "runtime.log", settings) as session:
        result = generate_graph_minutes(
            session,
            units,
            meeting_id="existing_pilot_" + args.input,
            output=args.output,
            metadata={"meeting_name": "Họp triển khai kho tài liệu Sao Khuê"},
            agenda=["Tổ chức tài liệu", "Phân quyền", "Phân công và tiến độ"],
        )
    (args.output / "text.txt").write_text(result["text"])
    report = result["report"]
    summary = {
        "wall_sec": time.perf_counter() - start,
        "input": args.input,
        "unit_count": len(units),
        "excluded": excluded,
        "calls": len(report["calls"]),
        "cached_calls": sum(c.get("cache_hit", False) for c in report["calls"]),
        "output_tokens": sum(c.get("generation_tokens", 0) for c in report["calls"]),
        "source_fallback_rate": report["coverage"]["source_fallback_rate"],
        "claim_id_coverage_complete": report["coverage"]["claim_id_coverage_complete"],
        "semantic_accuracy_verified": False,
    }
    save_json(args.output / "speed_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
