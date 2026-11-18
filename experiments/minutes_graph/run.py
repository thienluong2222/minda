"""Run A-F with real cached Qwen/E5; keep authored answers outside model input."""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "web_app/src"))

from docx import Document

from meeting_pipeline.minutes.doc_parser import parse_template_document
from meeting_pipeline.minutes.evidence_retrieval import IndexedTurn
from meeting_pipeline.minutes.graph_contracts import default_style
from meeting_pipeline.minutes.graph_inputs import make_graph_units
from meeting_pipeline.minutes.graph_pipeline import generate_graph_minutes, save_json
from meeting_pipeline.minutes.graph_writer import numeric_values
from meeting_pipeline.minutes.model_runtime import ModelSession
from meeting_pipeline.minutes.schema_mapper import M0RuleSchemaMapper
from meeting_pipeline.minutes.style_memory import learn_style_rules
from meeting_pipeline.minutes.text_engine import MinutesOptions, TextEngine, make_units

DATA = ROOT / "web_app/artifacts/llm-next-round-v2-20261026/data"
OUT = ROOT / "reports/minutes_graph/20261108"


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def source_payload(row):
    return json.loads(next(m["content"] for m in row["messages"] if m["role"] == "user"))


def reference_payload(row):
    return json.loads(next(m["content"] for m in row["messages"] if m["role"] == "assistant"))


def turns_for(payload):
    return [
        IndexedTurn(
            turn_id=u["unit_id"],
            speaker_label=u.get("speaker_label", ""),
            speaker_id=u.get("speaker_label", ""),
            start_sec=float(i),
            end_sec=float(i + 1),
            text=u["text"],
            tokens=[],
            source_id="existing_authored_transcript",
            clip_path=None,
            asr_status="transcribed",
            needs_review=False,
            confidence=None,
        )
        for i, u in enumerate(payload["units"])
    ]


def training_style():
    profile = default_style()
    profile.profile_id = "authored_train_style_surrogate"
    profile.provenance = "existing_authored_train_references_not_independent_human_feedback"
    edits = []
    # Use only a frozen prefix of TRAIN; never validation/test references.
    for row in read_rows(DATA / "train.jsonl")[:24]:
        payload = source_payload(row)
        ref = reference_payload(row)
        before = " ".join(
            u.get("speaker_label", "").split(" — ")[0] + " phát biểu rằng " + u["text"]
            for u in payload["units"]
        )
        after = "\n\n".join(p["text"] for p in ref.get("paragraphs", []))
        edits.append(
            {
                "edit_id": row["id"],
                "before": before,
                "after": after,
                "approved": True,
                "facts_unchanged": True,
                "names": [u.get("speaker_label", "").split(" — ")[0] for u in payload["units"]],
            }
        )
    profile, audit = learn_style_rules(profile, edits)
    return profile, audit


def metrics(text, source, paragraphs, covered, total, fallback, report):
    words = re.findall(r"\w+", text.casefold())
    source_words = re.findall(r"\w+", source.casefold())
    sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
    return {
        "output_words": len(words),
        "source_words": len(source_words),
        "word_ratio": len(words) / max(1, len(source_words)),
        "paragraph_count": len(paragraphs),
        "mean_paragraph_words": sum(len(p.split()) for p in paragraphs) / max(1, len(paragraphs)),
        "duplicate_sentence_rate": 1
        - len(set(s.casefold() for s in sentences)) / max(1, len(sentences)),
        "introduced_numeric_value_count": sum(
            (numeric_values("\n".join(paragraphs)) - numeric_values(source)).values()
        ),
        "id_coverage": covered / max(1, total),
        "source_fallback_rate": fallback,
        "semantic_accuracy_verified": False,
        "logical_generation_tokens": sum(
            c.get("generation_tokens", 0) for c in report.get("calls", [])
        ),
        "observed_cache_hits": sum(bool(c.get("cache_hit")) for c in report.get("calls", [])),
        "observed_model_calls": len(report.get("calls", [])),
    }


def export_docx(path, title, paragraphs):
    document = Document()
    document.add_heading(title, level=0)
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    document.save(path)
    reopened = Document(path)
    assert [p.text for p in reopened.paragraphs[1:]] == paragraphs
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["new_dev", "test", "valid"], default="test")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--per-group", type=int)
    parser.add_argument("--include-id", nargs="*", default=[])
    parser.add_argument("--variants", nargs="+", default=list("ABCDEF"))
    parser.add_argument("--output", type=Path, default=OUT / "ablations")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--integration", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    rows = read_rows(DATA / f"{args.split}.jsonl")
    by_id = {row["id"]: row for row in rows}
    if args.per_group:
        groups = {}
        for row in rows:
            groups.setdefault(row.get("group_id", row["id"]), []).append(row)
        selected = []
        for values in groups.values():
            ordered = sorted(
                values, key=lambda row: len(json.dumps(source_payload(row), ensure_ascii=False))
            )
            # Select on source length before running any candidate, never on outcomes.
            positions = [
                round(i * (len(ordered) - 1) / max(1, args.per_group - 1))
                for i in range(min(args.per_group, len(ordered)))
            ]
            selected.extend(ordered[i] for i in sorted(set(positions)))
        rows = selected
    if args.limit:
        rows = rows[: args.limit]
    existing = {row["id"] for row in rows}
    for identifier in args.include_id:
        if identifier not in by_id:
            parser.error(f"Unknown source ID: {identifier}")
        if identifier not in existing:
            rows.append(by_id[identifier])
            existing.add(identifier)
    profile, style_audit = training_style()
    save_json(
        output / "style_training.json",
        {"profile": profile.model_dump(), "audit": style_audit, "not_actual_user_feedback": True},
    )
    protocol = {
        "corpus": str(DATA),
        "split": args.split,
        "case_count": len(rows),
        "evaluation_unit": "authored transcript-section examples; not independent full recordings",
        "selected_ids": [row["id"] for row in rows],
        "sampling": (
            "shortest source per family plus explicit additional source IDs"
            if args.per_group == 1
            else "source-length stratified within all scenario families"
            if args.per_group
            else "all"
        ),
        "per_group": args.per_group,
        "explicit_additional_source_ids": args.include_id,
        "scenario_groups": sorted({r.get("group_id", r["id"]) for r in rows}),
        "variants": args.variants,
        "reference_answers_in_model_input": False,
        "agenda_titles_withheld": True,
        "weight_fine_tuning": False,
        "runtime_parser": getattr(
            sys.modules[ModelSession.__module__], "RUNTIME_SIGNATURE", "mlx-lm-0.29.1-temp0-v1"
        ),
        "human_style_evaluation": "not_available",
        "annotation_quality": "authored_synthetic_not_independent_human_gold",
        "test_set_used_for_engineering_debugging": True,
        "evaluation_status": (
            "engineering regression and ablation; not untouched held-out generalization"
        ),
        "style_training": "frozen_first_24_train_examples_only",
        "latency": "observed shared cache; do not rank uncached standalone latency",
        "timestamp_fields": "synthetic turn order, not observed audio timing",
        "platform": platform.platform(),
    }
    save_json(output / "protocol.json", protocol)
    template = output / "minimal_template.docx"
    if not template.exists():
        document = Document()
        document.add_paragraph("Nội dung cuộc họp:")
        document.add_paragraph("........................................")
        document.save(template)
    body = M0RuleSchemaMapper().propose_schema(parse_template_document(template)).fields[0]
    all_results = []
    with ModelSession(output / "model_runtime.log") as session:
        save_json(output / "model_settings.json", session.settings.model_dump())
        for row in rows:
            payload = source_payload(row)
            turns = turns_for(payload)
            units, _ = make_graph_units(turns)
            source = " ".join(u["text"] for u in payload["units"])
            prepared = None
            for variant in args.variants:
                directory = output / row["id"] / variant
                summary_path = directory / "summary.json"
                if args.resume and summary_path.exists():
                    all_results.append(json.loads(summary_path.read_text()))
                    continue
                directory.mkdir(parents=True, exist_ok=True)
                started = time.perf_counter()
                call_start = len(session.calls)
                print(f"START {row['id']} {variant}", flush=True)
                if variant == "A":
                    legacy_units, _ = make_units(turns)
                    fact, topics = TextEngine(session, row["id"]).write_general(
                        legacy_units,
                        MinutesOptions(
                            use_model=True, graph_enabled=False, mode="general", use_fcm=True
                        ),
                        turns,
                        body,
                    )
                    text = str(fact.value)
                    paragraphs = [
                        item["text"] for section in topics["sections"] for item in section["items"]
                    ]
                    report = {"calls": session.calls[call_start:]}
                    total = len(legacy_units)
                    covered = len(topics.get("covered_unit_ids", []))
                    fallback = None
                    save_json(directory / "topics.json", topics)
                    save_json(directory / "model_report.json", report)
                else:
                    result = generate_graph_minutes(
                        session,
                        units,
                        meeting_id=row["id"],
                        output=directory,
                        variant=variant,
                        prepared_events=prepared,
                        metadata={"meeting_id": row["id"]},
                        style=profile,
                    )
                    if variant != "B":
                        prepared = result["prepared_events"]
                    text, report = result["text"], result["report"]
                    paragraphs = [
                        p.text for section in result["sections"] for p in section.paragraphs
                    ]
                    total = report["coverage"]["included_claims"]
                    covered = report["coverage"]["covered_claims"]
                    fallback = report["coverage"]["source_fallback_rate"]
                (directory / "completed_text.txt").write_text(text, encoding="utf-8")
                document_hash = export_docx(
                    directory / "completed.docx", "Biên bản cuộc họp", paragraphs
                )
                summary = {
                    "id": row["id"],
                    "group_id": row.get("group_id", row["id"]),
                    "variant": variant,
                    "input_sha256": hashlib.sha256(source.encode()).hexdigest(),
                    "docx_sha256": document_hash,
                    "wall_sec_observed": round(time.perf_counter() - started, 3),
                    **metrics(text, source, paragraphs, covered, total, fallback, report),
                }
                save_json(summary_path, summary)
                all_results.append(summary)
                save_json(output / "results.json", all_results)
                print(json.dumps(summary, ensure_ascii=False), flush=True)
    save_json(output / "results.json", all_results)
    with (output / "results.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(all_results[0]))
        writer.writeheader()
        writer.writerows(all_results)
    if args.integration:
        subprocess.run([sys.executable, "-m", "experiments.minutes_graph.integration"], check=True)


if __name__ == "__main__":
    main()
