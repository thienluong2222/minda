"""FCM/agenda -> evidence graph -> plan -> paragraphs -> checks -> template facts."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from meeting_pipeline.minutes.graph_builder import (
    build_graph,
    extract_events,
    fallback_event,
    validate_graph,
)
from meeting_pipeline.minutes.graph_contracts import (
    INACTIVE_STATES,
    Event,
    GraphUnit,
    MeetingGraph,
    StyleProfile,
    Variant,
    digest,
)
from meeting_pipeline.minutes.graph_editorial import name_topics
from meeting_pipeline.minutes.graph_inputs import make_graph_units
from meeting_pipeline.minutes.graph_plan import ContentPlan
from meeting_pipeline.minutes.graph_relations import connect_events
from meeting_pipeline.minutes.graph_topics import discover_topics, refine_topics
from meeting_pipeline.minutes.graph_writer import (
    event_source_text,
    finalize_graph_sections,
    plan_sections,
    polish_sections,
    write_sections,
)
from meeting_pipeline.minutes.model_runtime import ModelRuntimeError, ModelSession
from meeting_pipeline.minutes.schemas import (
    EvidenceRef,
    FactStatus,
    MeetingFact,
    PlaceholderType,
    SemanticFieldType,
)
from meeting_pipeline.minutes.structured_fields import structured_facts
from meeting_pipeline.minutes.style_memory import profile_from_metadata

GRAPH_FILES = (
    "meeting_graph.json",
    "content_plan.json",
    "content_plan_prepared.json",
    "verification.json",
    "coverage.json",
    "style_profile.json",
    "input_snapshot.json",
    "graph_checkpoint.json",
)


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def generate_graph_minutes(
    session: Any,
    units: list[GraphUnit],
    *,
    meeting_id: str,
    output: Path,
    metadata: dict[str, Any] | None = None,
    agenda: list[str] | None = None,
    variant: Variant = "F",
    mode: str = "general",
    use_fcm: bool = True,
    fixed_clusters: int | None = None,
    style: StyleProfile | None = None,
    prepared_events: tuple[list[Event], list[dict[str, Any]], list[str]] | None = None,
    verify: bool = True,
) -> dict[str, Any]:
    if not units:
        raise ModelRuntimeError("Không có transcript hợp lệ để xây đồ thị.")
    metadata = metadata or {}
    output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    start_calls = len(session.calls)
    settings = session.settings.model_dump()
    snapshot = {
        "units": [u.model_dump() for u in units],
        "metadata": metadata,
        "agenda": agenda or [],
        "variant": variant,
        "settings": settings,
        "mode": mode,
        "style": style.model_dump() if style else None,
    }
    save_json(output / "input_snapshot.json", {**snapshot, "sha256": digest(snapshot)})
    topics, vectors = discover_topics(
        session,
        units,
        agenda=agenda,
        use_fcm=use_fcm and variant != "C",
        fixed_clusters=fixed_clusters,
    )
    checkpoint_key = digest({"snapshot": snapshot, "phase": "events-v2-atomic"})

    def checkpoint(events: list[Event], relations: list[dict[str, Any]]) -> None:
        save_json(
            output / "graph_checkpoint.json",
            {
                "key": checkpoint_key,
                "processed_events": len(events),
                "processed_relations": len(relations),
                "completed": len({e.unit_ids[0] for e in events}) == len(units),
            },
        )

    if variant == "B":
        events, relations, warnings = [fallback_event(u) for u in units], [], []
    elif prepared_events is not None:
        events, relations, warnings = prepared_events
    else:
        # ModelSession's content-addressed response cache also resumes partial batches.
        events, relations, warnings = extract_events(session, units, vectors, checkpoint)
    if variant != "B":
        relations = connect_events(session, events, relations, units)
        provisional = build_graph(meeting_id, units, events, topics, relations, metadata=metadata)
        topics = refine_topics(topics, units, provisional.events, provisional.edges)
    topics = name_topics(session, units, events, topics)
    graph = build_graph(
        meeting_id,
        units,
        events,
        topics,
        relations,
        soft=variant in {"E", "F"},
        metadata=metadata,
        warnings=warnings,
    )
    errors = validate_graph(graph)
    if errors:
        raise ModelRuntimeError("Đồ thị không hợp lệ: " + ", ".join(errors))
    save_json(output / "meeting_graph.json", graph.model_dump(mode="json"))
    sections, ledger = plan_sections(
        graph,
        use_graph=variant != "B",
        soft=variant in {"E", "F"},
        mode=mode,
        information_budget=getattr(session.settings, "information_budget_per_topic", 0),
        editorial_layout=mode == "general",
    )
    events_by_id = {event.event_id: event for event in graph.events}
    plan = ContentPlan(
        graph_id=graph.graph_id,
        transcript_version_id=graph.metadata.get("transcript_version_id"),
        sections=sections,
        ledger=ledger,
        review_items=[
            {**row, "text": events_by_id[row["claim_id"]].text}
            for row in ledger
            if row.get("needs_review")
        ],
    )
    plan.seal()
    save_json(output / "content_plan_prepared.json", plan.prepared())
    active_style = style or profile_from_metadata(metadata)
    if variant != "F":
        active_style = active_style.model_copy(
            update={
                "rules": [r for r in active_style.rules if not r.rule_id.startswith("learned_")]
            }
        )
    save_json(output / "style_profile.json", active_style.model_dump())

    audit = write_content_plan(
        session, graph, plan, active_style, output, variant=variant, verify=verify
    )
    text, topics, coverage = publish_content_plan(output, graph, plan, audit, mode)
    report = {
        "engine": "fcm_evidence_graph",
        "editorial_version": "3.0",
        "variant": variant,
        "graph_id": graph.graph_id,
        "plan_id": plan.plan_id,
        "model_id": session.settings.model_id,
        "model_revision": session.settings.model_revision,
        "embedding_id": session.settings.embedding_id,
        "embedding_revision": session.settings.embedding_revision,
        "calls": session.calls[start_calls:],
        "warnings": graph.warnings,
        "unit_count": len(units),
        "event_count": len(events),
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "cluster_count": topics["cluster_count"],
        "coverage": coverage,
        "outline_section_count": len(plan.sections),
        "review_claim_count": len(plan.review_items),
        "wall_sec": round(time.perf_counter() - started, 3),
        "semantic_accuracy_verified": False,
        "peak_mlx_gb": max(
            (c.get("peak_mlx_gb", 0) for c in session.calls[start_calls:]), default=0
        ),
    }
    save_json(output / "model_report.json", report)
    return {
        "graph": graph,
        "sections": plan.sections,
        "text": text,
        "topics": topics,
        "report": report,
        "prepared_events": (events, relations, warnings),
    }


def write_content_plan(
    session: Any,
    graph: MeetingGraph,
    plan: ContentPlan,
    style: StyleProfile,
    output: Path,
    *,
    variant: Variant,
    verify: bool = True,
    changed: set[str] | None = None,
) -> list[dict]:
    sections = [
        section for section in plan.sections if changed is None or section.section_id in changed
    ]

    def writing_checkpoint(_current: Any, audit: Any) -> None:
        if audit:
            item = audit[-1]
            key = digest([plan.plan_id, item["section_id"], item["claim_ids"]])[:20]
            save_json(output / "packets" / (key + ".json"), item)

    sections, audit = write_sections(
        session,
        graph,
        sections,
        use_graph=variant != "B",
        soft=variant in {"E", "F"},
        style=style,
        verify=verify,
        checkpoint=writing_checkpoint,
    )
    audit.extend(
        polish_sections(
            session,
            graph,
            sections,
            style,
            verify=verify,
            use_graph=variant != "B",
            soft=variant in {"E", "F"},
        )
    )
    finalize_graph_sections(graph, sections)
    return audit


def publish_content_plan(
    output: Path, graph: MeetingGraph, plan: ContentPlan, audit: list[dict], mode: str
) -> tuple[str, dict, dict]:
    sections, ledger = plan.sections, plan.ledger
    included = {row["claim_id"] for row in ledger if row["disposition"] in {"included", "merged"}}
    covered = {
        cid
        for section in sections
        for paragraph in section.paragraphs
        for cid in paragraph.claim_ids
    }
    source_ids = {uid for section in sections for p in section.paragraphs for uid in p.evidence_ids}
    fallback_claims = {
        cid
        for section in sections
        for p in section.paragraphs
        if p.verification == "source_fallback"
        for cid in p.claim_ids
    }
    aligned_claims = {
        alignment.claim_id
        for section in sections
        for paragraph in section.paragraphs
        if paragraph.verification == "checked"
        for alignment in paragraph.alignments
    }
    coverage = {
        "included_claims": len(included),
        "covered_claims": len(covered),
        "claim_id_coverage_complete": included == covered,
        "source_unit_count": len(graph.units),
        "merged_claims": sum(row["disposition"] == "merged" for row in ledger),
        "context_only_claims": sum(row["disposition"] == "context_only" for row in ledger),
        "cited_unit_count": len(source_ids),
        "source_fallback_claims": len(fallback_claims),
        "source_fallback_rate": len(fallback_claims) / max(1, len(included)),
        "model_aligned_claims": len(aligned_claims),
        "ledger": ledger,
        "semantic_completeness_verified": False,
    }
    if included != covered:
        raise ModelRuntimeError("Bản viết không bao phủ đủ các claim trong kế hoạch.")
    plan.phase = "written"
    save_json(output / "content_plan.json", plan.model_dump())
    save_json(output / "coverage.json", coverage)
    compatibility_sections = [
        {
            "title": section.title,
            "items": [
                {
                    "text": p.text,
                    "unit_ids": p.evidence_ids,
                    "claim_ids": p.claim_ids,
                    "verification": p.verification,
                }
                for p in section.paragraphs
            ],
            "unit_ids": list(
                dict.fromkeys(uid for p in section.paragraphs for uid in p.evidence_ids)
            ),
        }
        for section in sections
        if section.paragraphs
    ]
    written_sections = [section for section in sections if section.paragraphs]
    text = "\n\n".join(
        (section.title + "\n" if len(written_sections) > 1 and mode == "general" else "")
        + "\n\n".join(p.text for p in section.paragraphs)
        for section in written_sections
    )
    topics = dict(graph.topics)
    topics.update(
        sections=compatibility_sections,
        coverage_complete=included == covered,
        units=[u.model_dump() for u in graph.units],
        covered_unit_ids=sorted(source_ids),
        graph_id=graph.graph_id,
    )
    save_json(output / "topics.json", topics)
    save_json(
        output / "verification.json",
        {
            "checks": audit,
            "semantic_accuracy_verified": False,
            "note": "Rule/model checks are diagnostics, not independent semantic certification.",
        },
    )
    return text, topics, coverage


def graph_narrative_values(
    graph: MeetingGraph,
    sections: list,
    schema: Any,
    turns: list[Any],
    run_id: str,
    body_field_id: str,
    text: str,
) -> dict[str, MeetingFact]:
    by_turn = {turn.turn_id: turn for turn in turns}
    units = {unit.unit_id: unit for unit in graph.units}
    events = {event.event_id: event for event in graph.events}
    selected = {cid for section in sections for p in section.paragraphs for cid in p.claim_ids}

    def refs_for(unit_ids: list[str]) -> list[EvidenceRef]:
        turn_ids = dict.fromkeys(units[uid].turn_id for uid in unit_ids if uid in units)
        return [
            EvidenceRef(
                run_id=run_id,
                turn_id=turn_id,
                source_id=turn.source_id,
                start_sec=turn.start_sec,
                end_sec=turn.end_sec,
                clip_path=turn.clip_path,
                text_snippet=turn.text,
            )
            for turn_id in turn_ids
            if (turn := by_turn.get(turn_id))
        ]

    result = {
        body_field_id: MeetingFact(
            field_id=body_field_id,
            value=text,
            status=FactStatus.NEEDS_REVIEW,
            evidence_refs=refs_for(
                [uid for s in sections for p in s.paragraphs for uid in p.evidence_ids]
            ),
            reason="Tổng hợp từ dàn ý và đoạn nguồn. Cần rà soát nội dung.",
        )
    }
    for field in schema.fields:
        if field.semantic_type == SemanticFieldType.DECISION_LIST:
            kinds = {"decision", "vote"}
        elif field.semantic_type == SemanticFieldType.ACTION_ITEM:
            kinds = {"task"}
        else:
            continue
        chosen = [
            event
            for event in graph.events
            if event.event_id in selected
            and event.kind in kinds
            and event.lifecycle not in INACTIVE_STATES
        ]
        result[field.field_id] = MeetingFact(
            field_id=field.field_id,
            value="\n".join(event_source_text(event, units, events) for event in chosen) or None,
            status=FactStatus.NEEDS_REVIEW if chosen else FactStatus.UNKNOWN,
            evidence_refs=refs_for(
                [
                    uid
                    for event in chosen
                    for uid in [
                        *event.unit_ids,
                        *(anchor.unit_id for anchor in event.state_evidence),
                    ]
                ]
            ),
            reason="Sự kiện còn hiệu lực và thuộc dàn ý đã chọn. Cần đối chiếu phạm vi.",
        )
    return result


def run_graph_text_models(
    schema: Any,
    document_graph: Any,
    turns: list[Any],
    run_dir: Path,
    options: Any,
    *,
    preserve_schema: bool = False,
    meeting_metadata: dict[str, Any] | None = None,
) -> tuple[Any, list[MeetingFact], dict[str, Any]]:
    from meeting_pipeline.minutes.text_engine import FREE_TYPES, TextEngine

    metadata = meeting_metadata or {}
    output = run_dir / "minutes"
    units, excluded = make_graph_units(turns, metadata)
    anchors = {a.anchor_id: a for a in document_graph.all_anchors}
    with ModelSession(output / "model_runtime.log") as session:
        engine = TextEngine(session, run_dir.name)
        candidates = [
            u
            for u in units
            if not u.user_edited and (session.settings.correction_policy == "all" or u.needs_review)
        ]
        corrections = engine.correct(candidates) if options.correct_transcript else []
        if not preserve_schema:
            schema = engine.map_schema(schema, document_graph)
        base = structured_facts(
            schema, document_graph, turns, run_dir.name, meeting_metadata=metadata
        )
        facts_by_id = {f.field_id: f for f in base}
        # Reuse the field extractor for scalar/custom slots, not narrative body generation.
        scalar_schema = schema.model_copy(
            update={
                "fields": [
                    f
                    for f in schema.fields
                    if f.semantic_type not in FREE_TYPES
                    and anchors[f.anchor_id].placeholder_type
                    not in {
                        PlaceholderType.SIGNATURE_BLOCK,
                        PlaceholderType.FIXED_TEXT,
                    }
                    and not (
                        f.field_id in facts_by_id
                        and facts_by_id[f.field_id].status == FactStatus.SUPPORTED
                        and facts_by_id[f.field_id].value not in (None, "")
                    )
                ]
            }
        )
        for fact in engine.extract_fields(scalar_schema, document_graph, turns, units):
            previous = facts_by_id.get(fact.field_id)
            if (
                not previous
                or previous.status != FactStatus.SUPPORTED
                or previous.value in (None, "")
            ):
                facts_by_id[fact.field_id] = fact
        result = generate_graph_minutes(
            session,
            units,
            meeting_id=str(metadata.get("meeting_id", run_dir.name)),
            output=output,
            metadata=metadata,
            agenda=list(metadata.get("agenda", [])),
            mode=options.mode,
            use_fcm=options.use_fcm,
            fixed_clusters=options.clusters,
        )
        graph = result["graph"]
        body_fields = [
            f
            for f in schema.fields
            if f.semantic_type
            in {
                SemanticFieldType.DISCUSSION_SUMMARY,
                SemanticFieldType.MEETING_AGENDA,
            }
            and anchors[f.anchor_id].placeholder_type
            not in {
                PlaceholderType.SIGNATURE_BLOCK,
                PlaceholderType.FIXED_TEXT,
            }
        ]
        if options.content_field_id:
            body_fields = [f for f in body_fields if f.field_id == options.content_field_id]
        if not body_fields:
            raise ModelRuntimeError(
                "Mẫu chưa có vùng nội dung phù hợp; cần xác định vùng nội dung biên bản."
            )
        # Dotted continuation slots with the same label share one narrative placement.
        primary = body_fields[0]
        projected = graph_narrative_values(
            graph,
            result["sections"],
            schema,
            turns,
            run_dir.name,
            primary.field_id,
            result["text"],
        )
        facts_by_id.update(
            {
                fid: fact
                for fid, fact in projected.items()
                if fid == primary.field_id
                or fact.status != FactStatus.UNKNOWN
                or fid not in facts_by_id
            }
        )
        for field in body_fields[1:]:
            if (field.raw_label, field.section, field.semantic_type) == (
                primary.raw_label,
                primary.section,
                primary.semantic_type,
            ):
                facts_by_id[field.field_id] = MeetingFact(
                    field_id=field.field_id,
                    value="",
                    status=FactStatus.SUPPORTED,
                    reason="Vùng tiếp nối của cùng nội dung.",
                )
            else:
                # Independent body slots require explicit semantic allocation.
                facts_by_id[field.field_id] = MeetingFact(
                    field_id=field.field_id,
                    status=FactStatus.UNKNOWN,
                    reason=(
                        "Vùng nội dung riêng cần xác định phạm vi; không sao chép toàn biên bản."
                    ),
                )
        report = result["report"]
        report.update(
            options=options.model_dump(mode="json"),
            calls=session.calls,
            warnings=[*report["warnings"], *engine.warnings],
            excluded_turns=excluded,
            processed_turn_ids=list(dict.fromkeys(u.turn_id for u in units)),
            body_field_id=primary.field_id,
            continuation_fields=[f.field_id for f in body_fields[1:]],
        )
        save_json(output / "model_report.json", report)
        save_json(output / "configuration.json", options.model_dump(mode="json"))
        save_json(output / "corrections.json", corrections)
        save_json(output / "corrected_transcript.json", [u.model_dump() for u in units])
    return schema, list(facts_by_id.values()), report
