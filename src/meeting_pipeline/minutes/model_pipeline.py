"""Text-only orchestration shared by web regeneration and the real-model benchmark."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from meeting_pipeline.minutes.evidence_retrieval import IndexedTurn
from meeting_pipeline.minutes.model_runtime import ModelRuntimeError, ModelSession
from meeting_pipeline.minutes.schemas import (
    DocGraph,
    FactStatus,
    MeetingFact,
    PlaceholderType,
    SemanticFieldType,
    TemplateSchema,
)
from meeting_pipeline.minutes.structured_fields import structured_facts
from meeting_pipeline.minutes.text_engine import (
    BODY_TYPES,
    FREE_TYPES,
    MinutesOptions,
    TextEngine,
    corrected_turns,
    make_units,
)


def run_text_models(
    schema: TemplateSchema,
    graph: DocGraph,
    turns: list[IndexedTurn],
    run_dir: Path,
    options: MinutesOptions,
    *,
    preserve_schema: bool = False,
    meeting_metadata: dict[str, Any] | None = None,
) -> tuple[TemplateSchema, list[MeetingFact], dict[str, Any]]:
    if options.graph_enabled:
        from meeting_pipeline.minutes.graph_pipeline import run_graph_text_models

        return run_graph_text_models(
            schema, graph, turns, run_dir, options, preserve_schema=preserve_schema,
            meeting_metadata=meeting_metadata,
        )
    start = time.perf_counter()
    units, excluded = make_units(turns)
    if not units:
        raise ModelRuntimeError("Không có transcript hợp lệ để tạo biên bản bằng LLM.")
    minutes_dir = run_dir / "minutes"
    minutes_dir.mkdir(parents=True, exist_ok=True)
    anchors = {a.anchor_id: a for a in graph.all_anchors}
    with ModelSession(minutes_dir / "model_runtime.log") as session:
        engine = TextEngine(session, run_dir.name)
        corrections = engine.correct(units) if options.correct_transcript else []
        if not preserve_schema:
            schema = engine.map_schema(schema, graph)
        # Multiple dotted lines for the same body slot are continuation capacity,
        # not separate requests to duplicate the whole discussion.
        effective = []
        seen = set()
        suppressed = []
        for field in schema.fields:
            anchor = anchors[field.anchor_id]
            key = (field.semantic_type, field.raw_label, field.section)
            if field.semantic_type in FREE_TYPES and anchor.is_multiline and key in seen:
                suppressed.append(field.field_id)
            else:
                effective.append(field)
                if anchor.is_multiline:
                    seen.add(key)
        working = schema.model_copy(update={"fields": effective})
        body = None
        candidates = [
            f
            for f in effective
            if f.semantic_type in BODY_TYPES
            and anchors[f.anchor_id].placeholder_type != PlaceholderType.SIGNATURE_BLOCK
        ]
        if options.mode == "general":
            if options.content_field_id:
                candidates = [f for f in candidates if f.field_id == options.content_field_id]
            if len(candidates) != 1:
                raise ValueError("Chế độ tổng quát cần chọn đúng một trường nội dung cuộc họp.")
            body = candidates[0]
        elif len(candidates) == 1:
            body = candidates[0]
        model_facts = engine.extract_fields(
            working, graph, turns, units, general_body=body.field_id if body else None
        )
        facts_by_id = {f.field_id: f for f in structured_facts(
            schema, graph, turns, run_dir.name, meeting_metadata=meeting_metadata
        )}
        facts_by_id.update({f.field_id: f for f in model_facts})
        topics: dict[str, Any] | None = None
        if body is not None:
            writing_options = options.model_copy(
                update={"use_fcm": options.mode == "general" and options.use_fcm}
            )
            body_fact, topics = engine.write_general(units, writing_options, turns, body)
            if options.mode == "detailed":
                body_fact.value = "\n".join(
                    item["text"] for section in topics["sections"] for item in section["items"]
                )
            facts_by_id[body_fact.field_id] = body_fact
            written = {
                item["unit_ids"][0]: item["text"]
                for section in topics["sections"]
                for item in section["items"]
            }
            decision_turns = {
                u.turn_id
                for u in units
                if re.search(
                    r"thống nhất như sau|quyết định|tôi kết luận|không dùng phương án|"
                    r"thực hiện đúng phần việc|trước khi công bố",
                    u.text.casefold(),
                )
            }
            # A conclusion often introduces several following sentences in the
            # same turn. Retain that turn's tasks and deadlines as well.
            decision_units = [u for u in units if u.turn_id in decision_turns]
            for field in effective:
                if field.semantic_type == SemanticFieldType.DECISION_LIST:
                    a = anchors[field.anchor_id]
                    if a.is_multiline and decision_units:
                        facts_by_id[field.field_id] = MeetingFact(
                            field_id=field.field_id,
                            value="\n".join(written.get(u.unit_id, u.text) for u in decision_units),
                            status=FactStatus.NEEDS_REVIEW,
                            evidence_refs=engine.evidence(
                                [u.unit_id for u in decision_units],
                                {u.unit_id: u for u in units},
                                {t.turn_id: t for t in turns},
                            ),
                            reason="Các phát biểu kết luận và nhiệm vụ; cần kiểm tra bản nháp.",
                        )
        facts = list(facts_by_id.values())
        for fact in facts:
            if fact.field_id in suppressed:
                fact.value = ""
                fact.status = FactStatus.SUPPORTED
                fact.evidence_refs = []
                fact.reason = "Dòng tiếp nối đã được điền ở ô nội dung đầu tiên."
        # Explicitly catalog suppressed continuation slots, never fill signatures.
        fact_ids = {f.field_id for f in facts}
        for field in schema.fields:
            if field.field_id not in fact_ids:
                facts.append(
                    MeetingFact(
                        field_id=field.field_id,
                        value="" if field.field_id in suppressed else None,
                        status=FactStatus.SUPPORTED
                        if field.field_id in suppressed
                        else FactStatus.UNKNOWN,
                        reason="Dòng tiếp nối hoặc vùng chữ ký được giữ nguyên.",
                    )
                )
        report = {
            "options": options.model_dump(mode="json"),
            "model_id": session.settings.model_id,
            "model_revision": session.settings.model_revision,
            "embedding_id": session.settings.embedding_id,
            "embedding_revision": session.settings.embedding_revision,
            "calls": session.calls,
            "warnings": engine.warnings,
            "excluded_turns": excluded,
            "unit_count": len(units),
            "processed_turn_ids": list(dict.fromkeys(u.turn_id for u in units)),
            "continuation_fields": suppressed,
            "body_field_id": body.field_id if body and options.mode == "general" else None,
            "wall_sec": round(time.perf_counter() - start, 3),
            "peak_mlx_gb": max((c.get("peak_mlx_gb", 0) for c in session.calls), default=0),
            "semantic_accuracy_verified": False,
        }
        template_text = " ".join(block.raw_text for block in graph.blocks).casefold()
        transcript_text = " ".join(turn.text for turn in turns).casefold()
        if "cùng ký" in template_text and re.search(r"chữ ký.{0,30}chưa", transcript_text):
            engine.warnings.append(
                "Mẫu có câu xác nhận ký sẵn, nhưng transcript nói chữ ký chưa có. "
                "Cần kiểm tra câu cố định này trước khi sử dụng biên bản."
            )
    payloads = {
        "corrections.json": corrections,
        "corrected_transcript.json": [
            {
                "turn_id": t.turn_id,
                "text": t.text,
                "speaker": t.speaker_label,
                "start_sec": t.start_sec,
                "end_sec": t.end_sec,
            }
            for t in corrected_turns(turns, units)
        ],
        "topics.json": topics,
        "model_report.json": report,
        "configuration.json": options.model_dump(mode="json"),
    }
    for name, data in payloads.items():
        (minutes_dir / name).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return schema, facts, report
