"""Run real cached Qwen/E5 on existing data; never feed reference facts to the model."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import time
import zipfile
from pathlib import Path

import docx

from meeting_pipeline.minutes.service import MinutesService
from meeting_pipeline.minutes.text_engine import MinutesOptions

ROOT = Path(__file__).resolve().parent.parent
PILOT = ROOT / "data/generated/fpt_tts_pilot_20261003"
ASR_RUN = ROOT / "data/meetings/test-c-enroll/runs/3e27f5fa-08d8-443d-a8d3-c44ef62b1479"
TEMPLATE = ASR_RUN / "template/normalized.docx"


def compare_package(original: Path, completed: Path) -> dict:
    with zipfile.ZipFile(original) as a, zipfile.ZipFile(completed) as b:
        changed = [
            name
            for name in a.namelist()
            if name not in b.namelist() or a.read(name) != b.read(name)
        ]
        return {
            "changed_parts": changed,
            "preserve_only_parts_unchanged": changed == ["word/document.xml"],
        }


def run_case(input_kind: str, variant: str, output: Path) -> dict:
    case_dir = output / f"{input_kind}_{variant}"
    case_dir.mkdir(parents=True, exist_ok=True)
    if input_kind == "reference":
        rows = json.loads((PILOT / "meeting_audio/reference_segments.json").read_text())
        segments = [
            {
                **row,
                "text": row["reference_text"],
                "speaker_id": row["reference_speaker_id"],
                "speaker_label": row["reference_speaker_id"].title(),
                "meeting_speaker_id": row["reference_speaker_id"],
                "speaker_status": "identified",
                "speaker_count": 1,
                "asr_status": "transcribed",
            }
            for row in rows
        ]
        (case_dir / "timeline.json").write_text(
            json.dumps({"segments": segments}, ensure_ascii=False, indent=2)
        )
    else:
        shutil.copy2(ASR_RUN / "timeline.json", case_dir / "timeline.json")
    options = MinutesOptions(
        use_model=variant != "baseline",
        mode="general" if variant in {"general", "fcm"} else "detailed",
        use_fcm=variant == "fcm",
    )
    start = time.perf_counter()
    result = MinutesService().process_template_for_run(TEMPLATE, case_dir, options=options)
    doc_path = Path(result["completed_docx"])
    doc = docx.Document(doc_path)
    text = "\n".join(p.text for p in doc.paragraphs)
    (case_dir / "completed_text.txt").write_text(text)
    facts = json.loads((case_dir / "minutes/facts.json").read_text())
    by_id = {f["field_id"]: f for f in facts}
    # These checks inspect slot values, not all document text (a rejected proposal
    # may legitimately appear in a narrative). Full semantic review is separate.
    slot_checks = {}
    for field, expected in (
        ("chairperson_name", "Minh"),
        ("secretary_name", "Lan"),
        ("voting_total", "3"),
        ("voting_approved_count", "3"),
        ("voting_rejected_count", "0"),
    ):
        actual = str(by_id.get(field, {}).get("value") or "")
        slot_checks[field] = {
            "value": actual,
            "expected": expected,
            "literal_match": expected.casefold() == actual.strip().casefold(),
        }
    topics_path = case_dir / "minutes/topics.json"
    topics = json.loads(topics_path.read_text()) if topics_path.is_file() else None
    report = result["model_report"]
    return {
        "input": input_kind,
        "variant": variant,
        "wall_sec": round(time.perf_counter() - start, 3),
        "completed_docx": str(doc_path.resolve().relative_to(ROOT)),
        "timeline_sha256": hashlib.sha256((case_dir / "timeline.json").read_bytes()).hexdigest(),
        "package": compare_package(TEMPLATE, doc_path),
        "slot_checks": slot_checks,
        "model_calls": len(report.get("calls", [])),
        "cache_hits": sum(bool(c.get("cache_hit")) for c in report.get("calls", [])),
        "peak_mlx_gb": report.get("peak_mlx_gb"),
        "peak_worker_rss_gb": max(
            (c.get("peak_worker_rss_gb", 0) for c in report.get("calls", [])), default=0
        ),
        "warnings": report.get("warnings", []),
        "unit_count": report.get("unit_count"),
        "processed_turn_count": len(report.get("processed_turn_ids", [])),
        "excluded_turn_count": len(report.get("excluded_turns", [])),
        "cluster_count": topics["cluster_count"] if topics else None,
        "unit_id_coverage_complete": topics["coverage_complete"] if topics else None,
        "semantic_accuracy_verified": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--inputs", nargs="+", choices=["reference", "asr"], default=["reference", "asr"]
    )
    parser.add_argument(
        "--variants",
        nargs="+",
        choices=["baseline", "detailed", "general", "fcm"],
        default=["baseline", "detailed", "general", "fcm"],
    )
    parser.add_argument("--output", type=Path, default=ROOT / "data/evaluations/llm_fcm_20261010")
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    report = {
        "platform": platform.platform(),
        "cases": [],
        "reference_facts_used_as_model_input": False,
        "limits": [
            "One synthetic meeting, no generalization claim.",
            "ID coverage does not establish semantic completeness.",
            "RSS is worker peak; MLX allocator excludes other system processes.",
        ],
    }
    for input_kind in args.inputs:
        for variant in args.variants:
            print(f"START {input_kind}/{variant}", flush=True)
            try:
                case = run_case(input_kind, variant, args.output)
                report["cases"].append(case)
                print(
                    json.dumps(
                        {
                            k: case[k]
                            for k in (
                                "input",
                                "variant",
                                "wall_sec",
                                "model_calls",
                                "warnings",
                                "cluster_count",
                                "unit_id_coverage_complete",
                            )
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            except Exception as exc:
                report["cases"].append({"input": input_kind, "variant": variant, "error": str(exc)})
                print(f"ERROR {input_kind}/{variant}: {exc}", flush=True)
            (args.output / "benchmark.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2)
            )
    if any("error" in case for case in report["cases"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
