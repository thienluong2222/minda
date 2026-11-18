"""Rewrite the changed sections from a pinned graph in a staged document version."""

import json
import time
from pathlib import Path

from meeting_backend.core.errors import AppError
from meeting_pipeline.minutes.evidence_retrieval import load_indexed_turns
from meeting_pipeline.minutes.graph_builder import validate_graph
from meeting_pipeline.minutes.graph_contracts import MeetingGraph, StyleProfile
from meeting_pipeline.minutes.graph_pipeline import (
    graph_narrative_values,
    publish_content_plan,
    save_json,
    write_content_plan,
)
from meeting_pipeline.minutes.graph_plan import ContentPlan, PlannedSectionEdit, revise_plan
from meeting_pipeline.minutes.model_runtime import ModelSession
from meeting_pipeline.minutes.schemas import FactStatus, PreviousFactEdit, TemplateSchema


def regenerate_outline(run: Path, payload: dict, source: dict, service) -> None:
    output = run / "minutes"
    plan = ContentPlan.model_validate_json((output / "content_plan.json").read_text())
    graph = MeetingGraph.model_validate_json((output / "meeting_graph.json").read_text())
    if plan.plan_id != payload["plan_id"] or validate_graph(graph):
        raise AppError("OUTLINE_STALE", "Dàn ý hoặc đồ thị đã thay đổi.", 409)
    edits = [PlannedSectionEdit.model_validate(section) for section in payload["sections"]]
    plan, changed = revise_plan(plan, graph, edits)
    save_json(output / "content_plan_prepared.json", plan.prepared())
    report = json.loads((output / "model_report.json").read_text())
    checks_path = output / "verification.json"
    checks = [
        check
        for check in json.loads(checks_path.read_text()).get("checks", [])
        if check.get("section_id") not in changed
    ]
    started = time.perf_counter()
    calls = []
    if any(section.section_id in changed and section.claim_ids for section in plan.sections):
        style = StyleProfile.model_validate_json((output / "style_profile.json").read_text())
        with ModelSession(output / "model_runtime.log") as session:
            checks.extend(
                write_content_plan(
                    session, graph, plan, style, output, variant=report["variant"], changed=changed
                )
            )
            calls = session.calls
        report.update(
            model_id=session.settings.model_id, model_revision=session.settings.model_revision
        )
    text, _, coverage = publish_content_plan(
        output, graph, plan, checks, source.get("options", {}).get("mode", "general")
    )
    report.update(
        plan_id=plan.plan_id,
        parent_plan_id=plan.parent_plan_id,
        coverage=coverage,
        calls=calls,
        wall_sec=round(time.perf_counter() - started, 3),
        regenerated_section_ids=sorted(changed),
        outline_section_count=len(plan.sections),
        peak_mlx_gb=max((call.get("peak_mlx_gb", 0) for call in calls), default=0),
    )
    save_json(output / "model_report.json", report)
    schema = TemplateSchema.model_validate_json((run / "template/schema.json").read_text())
    updated = graph_narrative_values(
        graph,
        plan.sections,
        schema,
        load_indexed_turns(run),
        run.name,
        report["body_field_id"],
        text,
    )
    current = {row["field_id"]: row for row in json.loads((output / "facts.json").read_text())}
    for field_id, fact in updated.items():
        prior = current.get(field_id, {})
        if prior.get("user_edited") and field_id != report["body_field_id"]:
            continue
        if prior.get("previous_edit"):
            fact.previous_edit = PreviousFactEdit.model_validate(prior["previous_edit"])
        elif prior.get("user_edited") and prior["value"] != fact.value:
            fact.previous_edit = PreviousFactEdit(
                value=prior["value"], minutes_version_id=source["_id"]
            )
        if fact.previous_edit:
            fact.status = FactStatus.CONFLICTING
        current[field_id] = fact.model_dump()
    service.update_facts_and_re_render(run, list(current.values()), mark_user_edited=False)
