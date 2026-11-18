"""Replay deterministic presentation fixes over actual stored generations, with guard equivalence.

This does not count as new model inference. It fails if a changed numeric guard could
have changed any recorded generation/check/repair path on these cases.
"""
# ruff: noqa: E402

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import types
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "web_app/src"))

from experiments.minutes_graph.run import DATA, OUT, export_docx, metrics, read_rows, source_payload
from meeting_pipeline.minutes.graph_builder import validate_event
from meeting_pipeline.minutes.graph_contracts import MeetingGraph, Section
from meeting_pipeline.minutes.graph_pipeline import save_json
from meeting_pipeline.minutes.graph_values import canonical_values


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def main():
    from meeting_pipeline.minutes.graph_writer import finalize_graph_sections

    original, output = OUT / "ablations_v2", OUT / "ablations_final"
    protocol = json.loads((original / "protocol.json").read_text())
    dataset = {r["id"]: r for r in read_rows(DATA / (protocol["split"] + ".jsonl"))}
    # Own archived source, captured before inference; no downloaded code is executed.
    previous = types.ModuleType("archived_graph_values")
    with zipfile.ZipFile(OUT / "frozen_generation_source_v2.zip") as archive:
        source = archive.read("web_app/src/meeting_pipeline/minutes/graph_values.py")
    exec(compile(source, "archived_graph_values.py", "exec"), previous.__dict__)
    jobs, checked_strings, checked_slots = [], 0, 0
    for case in protocol["selected_ids"]:
        for variant in protocol["variants"]:
            run = original / case / variant
            assert (run / "summary.json").is_file(), (case, variant)
            if variant == "A":
                continue
            old_graph = MeetingGraph.model_validate(
                json.loads((run / "meeting_graph.json").read_text())
            )
            available = {u.unit_id: u for u in old_graph.units}
            for event in old_graph.events:
                if event.extraction != "model":
                    continue
                item = {**event.model_dump(), "evidence_unit_ids": event.unit_ids[1:]}
                current = validate_event(item, available[event.unit_ids[0]], available)
                for field in ("owner", "deadline", "condition", "document_version"):
                    assert getattr(current, field) == getattr(event, field), (
                        "Literal slot guard changes an extracted field; rerun inference",
                        case,
                        variant,
                        event.event_id,
                        field,
                    )
                    checked_slots += 1
            for name in (
                "input_snapshot.json",
                "meeting_graph.json",
                "content_plan.json",
                "verification.json",
            ):
                for text in strings(json.loads((run / name).read_text())):
                    assert previous.canonical_values(text) == canonical_values(text), (
                        "Numeric normalization would change a recorded control path; "
                        "rerun inference",
                        case,
                        variant,
                        text,
                    )
                    checked_strings += 1
    for case in protocol["selected_ids"]:
        source = " ".join(u["text"] for u in source_payload(dataset[case])["units"])
        for variant in protocol["variants"]:
            before, run = original / case / variant, output / case / variant
            shutil.copytree(before, run, dirs_exist_ok=True)
            row = json.loads((run / "summary.json").read_text())
            if variant == "A":
                jobs.append(row)
                continue
            graph = MeetingGraph.model_validate(
                json.loads((run / "meeting_graph.json").read_text())
            )
            plan = json.loads((run / "content_plan.json").read_text())
            sections = [Section.model_validate(s) for s in plan["sections"]]
            events = {e.event_id: e for e in graph.events}
            for section in sections:
                for paragraph in section.paragraphs:
                    if paragraph.verification == "source_fallback":
                        assert paragraph.text == " ".join(
                            events[eid].text for eid in paragraph.claim_ids
                        ), "A source result is not from the frozen v2 inference process"
            lineage = [
                (s.section_id, p.claim_ids[:], p.evidence_ids[:])
                for s in sections
                for p in s.paragraphs
            ]
            sections = finalize_graph_sections(graph, sections)
            assert lineage == [
                (s.section_id, p.claim_ids, p.evidence_ids) for s in sections for p in s.paragraphs
            ]
            plan["sections"] = [s.model_dump() for s in sections]
            save_json(run / "content_plan.json", plan)
            paragraphs = [p.text for s in sections for p in s.paragraphs]
            text = "\n\n".join(
                (s.title + "\n" if len(sections) > 1 else "")
                + "\n\n".join(p.text for p in s.paragraphs)
                for s in sections
            )
            topics = json.loads((run / "topics.json").read_text())
            topics["sections"] = [
                {
                    "title": s.title,
                    "items": [
                        {
                            "text": p.text,
                            "unit_ids": p.evidence_ids,
                            "claim_ids": p.claim_ids,
                            "verification": p.verification,
                        }
                        for p in s.paragraphs
                    ],
                    "unit_ids": list(
                        dict.fromkeys(uid for p in s.paragraphs for uid in p.evidence_ids)
                    ),
                }
                for s in sections
            ]
            save_json(run / "topics.json", topics)
            (run / "completed_text.txt").write_text(text)
            report = json.loads((run / "model_report.json").read_text())
            report["presentation_replay"] = {
                "actual_generation_source": str(before),
                "new_llm_calls": 0,
                "numeric_guards_equivalent_for_all_recorded_strings": True,
                "changes": [
                    "attribute source-fallback quotes to original speakers",
                    "remove echoed schema titles",
                ],
            }
            save_json(run / "model_report.json", report)
            covered = report["coverage"]["covered_claims"]
            total = report["coverage"]["included_claims"]
            row.update(
                metrics(
                    text,
                    source,
                    paragraphs,
                    covered,
                    total,
                    report["coverage"]["source_fallback_rate"],
                    report,
                )
            )
            row.update(
                docx_sha256=export_docx(run / "completed.docx", "Biên bản cuộc họp", paragraphs),
                presentation_replayed=True,
            )
            save_json(run / "summary.json", row)
            jobs.append(row)
    protocol.update(
        model_generation="actual Qwen responses and recorded outcomes from ablations_v2",
        presentation=(
            "deterministic replay; no new inference, all recorded numeric guards equivalent"
        ),
        generation_source_snapshot="frozen_generation_source_v2.json",
        presentation_source_snapshot="frozen_generation_source_v3.json",
    )
    save_json(output / "protocol.json", protocol)
    save_json(output / "results.json", jobs)
    for name in ("style_training.json", "model_settings.json"):
        shutil.copy2(original / name, output / name)
    save_json(
        output / "replay_audit.json",
        {
            "actual_original_generations": len(jobs),
            "new_model_generations": 0,
            "guard_equivalence_strings_checked": checked_strings,
            "guard_equivalence_slots_checked": checked_slots,
            "original_protocol_sha256": hashlib.sha256(
                (original / "protocol.json").read_bytes()
            ).hexdigest(),
        },
    )
    print(
        json.dumps(
            {
                "replayed_cases": len(protocol["selected_ids"]),
                "variants": len(jobs),
                "guard_equivalence_strings_checked": checked_strings,
                "new_model_calls": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
