"""Close the validation report only when generation, exports, source checks and visual QA pass."""

from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports/minutes_graph/20261108"


def read(name):
    return json.loads((OUT / name).read_text())


def main():
    analysis = read("ablations_v5/analysis.json")
    protocol = read("ablations_v5/protocol.json")
    exports = read("end_to_end_final/results.json")
    qa = read("document_visual_qa.json")
    audit = read("task_changes.json")
    data = read("data_audit.json")
    reformat = read("export_reformat_audit.json")
    pilot_quality = read("pilot_quality_observations.json")
    assert analysis["complete"] and analysis["generation_count"] == 48
    assert {r["input"] for r in exports} == {"reference", "asr"}
    assert all(r["zip_integrity_pass"] and r["source_unchanged"] for r in exports)
    assert all(
        hashlib.sha256(Path(r["source_path"]).read_bytes()).hexdigest() == r["source_sha256"]
        for r in exports
    )
    assert all(r["all_pages_visually_inspected"] for r in qa["documents"])
    assert all(
        hashlib.sha256(Path(r["docx"]).read_bytes()).hexdigest() == r["docx_sha256"]
        for r in qa["documents"]
    )
    assert set(reformat) == {"reference", "asr"}
    assert all(
        r["all_paragraph_text_unchanged"] and r["zip_integrity_pass"] for r in reformat.values()
    )
    assert len(qa["documents"]) == len(exports)
    assert not audit["ui_changed_by_task"]
    assert audit["model_settings_unchanged"]
    for name, record in data["splits"].items():
        path = ROOT / "web_app/artifacts/llm-next-round-v2-20261026/data" / (name + ".jsonl")
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
    assert all(
        hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == h
        for p, h in read("frozen_current_source_v6.json").items()
    )
    tests = {}
    for name in ("root_unit_tests.xml", "web_unit_tests.xml", "backend_tests.xml"):
        suites = ET.parse(OUT / name).getroot().iter("testsuite")
        counts = {field: 0 for field in ("tests", "failures", "errors", "skipped")}
        for suite in suites:
            for field in counts:
                counts[field] += int(suite.get(field, 0))
        assert counts["failures"] == counts["errors"] == counts["skipped"] == 0
        tests[name] = counts
    structural = read("structural/source_contract_checks.json")
    clustering = read("structural/clustering_summary.json")
    summary = {
        "implementation": (
            "transcript -> agenda/FCM -> evidence graph -> plan -> narrative -> checks -> DOCX"
        ),
        "status": "implemented_and_validated_as_research_backend",
        "ui_changed": False,
        "ui_files_compared": audit["ui_files_checked"],
        "admin_preset_api": "/api/v1/admin/preset",
        "admin_flags": {"minutes_graph_enabled": True, "minutes_style_learning_enabled": True},
        "owner_scoped_graph_api": "/api/v1/meetings/{meeting_id}/minutes/graph",
        "tests": tests,
        "passed_test_total": sum(c["tests"] for c in tests.values()),
        "source_contract_cases": len(structural),
        "source_contract_checks_are_semantic_accuracy": False,
        "original_actual_ablation_documents": analysis["generation_count"],
        "ablation_source_cases": analysis["case_count"],
        "ablation_evaluation_unit": protocol["evaluation_unit"],
        "ablation_independent_families": analysis["independent_scenario_families"],
        "runtime_parser": protocol["runtime_parser"],
        "generation_source": "frozen_generation_source_v5.json",
        "export_source": "frozen_current_source_v6.json",
        "cache_policy": "Separate namespace; previously valid compatible responses reused",
        "variant_means": analysis["variant_means"],
        "clustering_test_means": [r for r in clustering if r["split"] == "test"],
        "clustering_total_runs": len(read("structural/clustering_per_document.json")),
        "long_structure_stress": read("structural/long_stress.json"),
        "end_to_end_service_exports": exports,
        "independent_pilot_meetings": 1,
        "pilot_transcript_versions": ["reference", "asr"],
        "pilot_quality_observations": pilot_quality,
        "presentation_only_reformat_audit": reformat,
        "visual_qa": qa,
        "weight_fine_tuning_executed": False,
        "style_learning": (
            "versioned owner-scoped rules from confirmed edits; train-only surrogate in F ablation"
        ),
        "human_secretary_style_quality_verified": False,
        "research_findings": [
            "FCM has not outperformed K-means on the existing labeled topic test set.",
            "Graph provenance coverage does not imply factual or natural-language quality.",
            "The final comparison includes the common JSON syntax fix; "
            "the earlier high fallback rates are superseded.",
            "F is not established as best by independent human assessment.",
            "The long-input result validates sparse graph structure, "
            "not long-meeting LLM semantics.",
        ],
        "fine_tuning_assessment": {
            "clustering": (
                "Tune membership/cluster-selection parameters on validation; "
                "do not call this neural fine-tuning."
            ),
            "embedding": (
                "Compare representations before training; current synthetic "
                "scores alone do not mandate weight tuning."
            ),
            "writer": (
                "Candidate for targeted SFT on concise drafting, complete claim IDs and "
                "faithful state/actor handling; calibrate checks on reviewed examples first."
            ),
            "verifier": (
                "Same-model checks need independent evaluation; "
                "do not treat their verdicts as semantic gold."
            ),
        },
        "reports": {
            "comparison": "ablations_v5/analysis.json",
            "blind_review": "ablations_v5/blind_review_unrated.json",
            "task_diff": "task_changes.patch",
        },
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(
        json.dumps(
            {
                "status": summary["status"],
                "passed_tests": summary["passed_test_total"],
                "actual_ablation_documents": analysis["generation_count"],
                "ui_changed": False,
            }
        )
    )


if __name__ == "__main__":
    main()
