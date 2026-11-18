"""Aggregate completed ablations; diagnostics never stand in for human factuality ratings."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from statistics import mean

import numpy as np
from docx import Document

from experiments.minutes_graph.run import (
    DATA,
    OUT,
    metrics,
    read_rows,
    reference_payload,
    source_payload,
)
from meeting_pipeline.minutes.graph_pipeline import save_json
from meeting_pipeline.minutes.graph_values import canonical_values


def words(text):
    return re.findall(r"\w+", text.casefold())


def token_f1(a, b):
    left, right = Counter(words(a)), Counter(words(b))
    overlap = sum((left & right).values())
    return 2 * overlap / max(1, sum(left.values()) + sum(right.values()))


def paired_group_interval(rows, variant, baseline, field):
    values = {(r["id"], r["variant"]): r for r in rows}
    groups = {}
    for row in rows:
        if row["variant"] != variant:
            continue
        old = values.get((row["id"], baseline))
        if not old or old.get(field) is None or row.get(field) is None:
            continue
        groups.setdefault(row["group_id"], []).append(row[field] - old[field])
    group_means = [mean(values) for _, values in sorted(groups.items())]
    if not group_means:
        return None
    rng = np.random.default_rng(20261108)
    sampled = rng.choice(group_means, size=(10000, len(group_means)), replace=True).mean(axis=1)
    return {
        "delta_group_macro_mean": mean(group_means),
        "bootstrap_95_percent_interval": np.quantile(sampled, [0.025, 0.975]).tolist(),
        "independent_scenario_families": len(group_means),
        "comparison": f"{variant} minus {baseline}",
        "not_a_human_quality_significance_test": True,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=OUT / "ablations_v2")
    args = parser.parse_args()
    directory = args.input.resolve()
    protocol = json.loads((directory / "protocol.json").read_text())
    dataset = {r["id"]: r for r in read_rows(DATA / (protocol["split"] + ".jsonl"))}
    expected = {
        (case, variant) for case in protocol["selected_ids"] for variant in protocol["variants"]
    }
    records, integrity = [], []
    for case, variant in sorted(expected):
        run = directory / case / variant
        row = json.loads((run / "summary.json").read_text())
        assert (row["id"], row["variant"]) == (case, variant)
        payload, reference = source_payload(dataset[case]), reference_payload(dataset[case])
        source = " ".join(u["text"] for u in payload["units"])
        reference_text = "\n\n".join(p["text"] for p in reference.get("paragraphs", []))
        paragraphs = [p.text for p in Document(run / "completed.docx").paragraphs[1:]]
        body = "\n\n".join(paragraphs)
        report = json.loads((run / "model_report.json").read_text())
        assert hashlib.sha256(source.encode()).hexdigest() == row["input_sha256"]
        assert (
            hashlib.sha256((run / "completed.docx").read_bytes()).hexdigest() == row["docx_sha256"]
        )
        measured = metrics(body, source, paragraphs, 0, 0, None, {})
        row.update(
            body_words=measured["output_words"],
            body_word_ratio=measured["word_ratio"],
            authored_reference_token_f1=token_f1(body, reference_text),
            source_token_f1=token_f1(body, source),
            first_person_mentions=len(re.findall(r"\btôi\b", body, re.I)),
            distinct_numeric_values_outside_source=len(
                set(canonical_values(body)) - set(canonical_values(source))
            ),
            repeated_numeric_occurrences_outside_source=sum(
                (canonical_values(body) - canonical_values(source)).values()
            ),
            closing_quote_repairs=sum(
                c.get("format_repair") == "redundant_closing_quote" for c in report.get("calls", [])
            ),
            compatible_legacy_cache_calls=sum(
                bool(c.get("legacy_compatible_cache")) for c in report.get("calls", [])
            ),
        )
        if variant != "A":
            graph = json.loads((run / "meeting_graph.json").read_text())
            audit = json.loads((run / "verification.json").read_text())["checks"]
            plan = json.loads((run / "content_plan.json").read_text())
            # Stable identities are guaranteed by the implementation, not evidence of entailment.
            assert len(graph["units"]) == len({u["unit_id"] for u in graph["units"]})
            reasons = Counter()
            for check in audit:
                if check["action"] == "accepted":
                    continue
                if "JSON" in check.get("reason", ""):
                    reasons["invalid_json"] += 1
                elif "claim_id" in check.get("reason", ""):
                    reasons["claim_id_mismatch"] += 1
                elif check.get("reason"):
                    reasons["other_runtime_or_schema_error"] += 1
                for item in check.get("checks", []):
                    reasons.update(item.get("risks", []))
            row.update(
                extraction_fallback_rate=(
                    mean(e["extraction"] == "source_fallback" for e in graph["events"])
                    if variant != "B"
                    else None
                ),
                writer_retry_count=sum(c["action"] == "retry" for c in audit),
                writer_fallback_batch_count=sum(c["action"] == "source_fallback" for c in audit),
                rejection_reasons=dict(reasons),
                generic_section_titles=sum(
                    bool(
                        re.match(
                            r"^(?:Vấn đề \d|Nội dung phát sinh|Đề mục ngắn có căn cứ)",
                            s["title"],
                            re.I,
                        )
                    )
                    for s in plan["sections"]
                ),
            )
        records.append(row)
        integrity.append(
            {"id": case, "variant": variant, "input_hash_matches": True, "docx_hash_matches": True}
        )
    aggregate_fields = [
        "body_word_ratio",
        "paragraph_count",
        "mean_paragraph_words",
        "source_fallback_rate",
        "authored_reference_token_f1",
        "first_person_mentions",
        "distinct_numeric_values_outside_source",
        "extraction_fallback_rate",
        "writer_retry_count",
        "writer_fallback_batch_count",
        "generic_section_titles",
        "closing_quote_repairs",
    ]
    variants = []
    for variant in protocol["variants"]:
        values = [r for r in records if r["variant"] == variant]
        aggregate = {
            "variant": variant,
            "cases": len(values),
            "id_coverage_minimum": min(r["id_coverage"] for r in values),
        }
        for field in aggregate_fields:
            valid = [r for r in values if r.get(field) is not None]
            if valid:
                group_values = {}
                for row in valid:
                    group_values.setdefault(row["group_id"], []).append(row[field])
                aggregate[field] = mean(mean(v) for v in group_values.values())
        variants.append(aggregate)
    summary = {
        "complete": len(records) == len(expected),
        "case_count": len(protocol["selected_ids"]),
        "generation_count": len(records),
        "independent_scenario_families": len(protocol["scenario_groups"]),
        "all_source_and_docx_hashes_match": True,
        "test_set_used_for_engineering_debugging": protocol.get(
            "test_set_used_for_engineering_debugging", False
        ),
        "variant_means": variants,
        "paired_diagnostics": {
            variant: {
                field: paired_group_interval(records, variant, "A", field)
                for field in [
                    "body_word_ratio",
                    "paragraph_count",
                    "authored_reference_token_f1",
                    "first_person_mentions",
                ]
            }
            for variant in protocol["variants"]
            if variant != "A"
        },
        "interpretation_limits": [
            "ID coverage checks provenance bookkeeping; "
            "it does not certify that every proposition is accurately expressed.",
            "Authored synthetic references are lexical proxies, "
            "not independent human gold or secretary-style ratings.",
            "Numeric value flags are diagnostics: "
            "repetition, spelling and association require source review.",
            "A has no equivalent source-fallback instrumentation; "
            "its missing fallback rate is not zero.",
            "Shared extraction and response caches invalidate "
            "standalone latency or throughput rankings.",
            "All final text still needs human review; seven scenario families "
            "cannot establish generalization to real long meetings.",
        ],
    }
    save_json(directory / "analysis.json", summary)
    save_json(directory / "diagnostics_per_case.json", records)
    save_json(directory / "integrity_checks.json", integrity)
    # Leave judgments blank. Candidate order is shuffled; no generated rating is called human gold.
    blind, key = [], []
    rng = np.random.default_rng(20261108)
    for case in protocol["selected_ids"]:
        candidates = []
        for index, variant in enumerate(rng.permutation(protocol["variants"]), start=1):
            label = f"candidate_{index}"
            paragraphs = [
                p.text
                for p in Document(directory / case / variant / "completed.docx").paragraphs[1:]
            ]
            candidates.append(
                {
                    "label": label,
                    "text": "\n\n".join(paragraphs),
                    "ratings_1_to_5": {
                        name: None
                        for name in (
                            "natural_secretary_style",
                            "factual_accuracy",
                            "important_content_coverage",
                            "coherence",
                            "conciseness",
                        )
                    },
                    "unsupported_or_missing_claims": [],
                    "reviewer_id": None,
                }
            )
            key.append({"id": case, "label": label, "variant": str(variant)})
        blind.append(
            {
                "id": case,
                "source_units": source_payload(dataset[case])["units"],
                "candidates": candidates,
            }
        )
    save_json(
        directory / "blind_review_unrated.json",
        {
            "status": "not_human_reviewed",
            "score_direction": "5 is best",
            "cases": blind,
        },
    )
    save_json(directory / "blind_review_mapping.json", key)
    flat = [{k: v for k, v in row.items() if k != "rejection_reasons"} for row in records]
    columns = list(dict.fromkeys(key for row in flat for key in row))
    with (directory / "diagnostics_per_case.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(flat)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
