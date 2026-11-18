"""Guard graph prose placement against scalar slots and repeated continuation holes."""

from __future__ import annotations

import json
import re
from pathlib import Path

from meeting_pipeline.minutes.graph_editorial import prose_presentation, readable_source
from meeting_pipeline.minutes.schemas import FactStatus, SemanticFieldType
from meeting_pipeline.minutes.structured_fields import scoped_field_ids, structured_facts


def guard_graph_export(run_dir, schema, document_graph, facts, turns, metadata=None):
    path = Path(run_dir) / "minutes"
    graph_file = path / "meeting_graph.json"
    if not graph_file.is_file():
        return facts
    graph = json.loads(graph_file.read_text())
    projected = graph.get("schema_version") == "2.0"
    plan_file = path / "content_plan.json"
    plan = json.loads(plan_file.read_text()) if plan_file.is_file() else {}
    result = {fact.field_id: fact for fact in facts}
    protected = scoped_field_ids(schema, document_graph)
    overrides = structured_facts(
        schema, document_graph, turns, Path(run_dir).name, metadata, scoped_only=True
    )
    repairs = []
    for fact in overrides:
        prior = result.get(fact.field_id)
        if fact.field_id not in protected or (prior and prior.user_edited):
            continue
        if prior and prior.value != fact.value:
            repairs.append({"field_id": fact.field_id, "reason": "scoped_scalar_slot"})
        result[fact.field_id] = fact

    events = {event["event_id"]: event for event in graph["events"]}
    decisions = [
        event
        for event in events.values()
        if event["kind"] == "decision"
        and event["lifecycle"] not in {"withdrawn", "superseded"}
        and not re.search(r"xin biểu quyết|ai tán thành.*giơ tay", event["text"], re.I)
    ]
    decision_ids = {event["event_id"] for event in decisions}
    sentences = []
    for section in plan.get("sections", []):
        for paragraph in section.get("paragraphs", []):
            if paragraph.get("verification") != "checked" or not decision_ids.intersection(
                paragraph["claim_ids"]
            ):
                continue
            for sentence in re.split(r"(?<=[.!?])\s+", paragraph["text"]):
                if re.match(
                    r"(?:Nhóm|Cuộc họp|Hội nghị|Các thành viên)\s+"
                    r"(?:(?:đã|sẽ)\s+)?(?:quyết định|thống nhất|thông qua)\b",
                    sentence,
                    re.I,
                ):
                    sentences.append(prose_presentation(sentence))
    conclusion = " ".join(dict.fromkeys(sentences[:3])) or " ".join(
        dict.fromkeys(readable_source(event["text"]) for event in decisions)
    )
    anchors = {anchor.anchor_id: anchor for anchor in document_graph.all_anchors}
    blocks = {block.block_id: block for block in document_graph.blocks}
    seen = set()
    for field in schema.fields:
        if field.field_id in protected or field.semantic_type not in {
            SemanticFieldType.DECISION_LIST,
            SemanticFieldType.ACTION_ITEM,
        }:
            continue
        prior = result.get(field.field_id)
        key = (field.semantic_type, field.raw_label, field.section)
        block = blocks[anchors[field.anchor_id].block_id]
        continuation = not re.search(r"\w", block.raw_text.replace("_", ""))
        repeated = key in seen and continuation
        seen.add(key)
        if prior and prior.user_edited:
            continue
        if repeated:
            value = ""
            reason = "Vùng tiếp nối của cùng kết luận/phân công; không sao chép lặp."
        else:
            value = (
                conclusion
                if field.semantic_type == SemanticFieldType.DECISION_LIST and not projected
                else (prior.value if prior else None)
            )
            reason = "Kết luận lấy từ nội dung có nguồn; loại lời mời biểu quyết."
        if prior and value != prior.value:
            result[field.field_id] = prior.model_copy(
                update={
                    "value": value,
                    "status": FactStatus.NEEDS_REVIEW if value else FactStatus.SUPPORTED,
                    "reason": reason,
                }
            )
            repairs.append({"field_id": field.field_id, "reason": "narrative_continuation"})

    if repairs:
        report_file = path / "model_report.json"
        report = json.loads(report_file.read_text()) if report_file.is_file() else {}
        report.setdefault("export_repairs", []).extend(repairs)
        _save(report_file, report)
    return list(result.values())


def _save(path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)
