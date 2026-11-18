"""Sparse, quoted discourse relations; source scope and transitions stay validated."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

from meeting_pipeline.minutes.graph_builder import GROUNDING, RELATIONS, bounded_batches
from meeting_pipeline.minutes.graph_contracts import FACT_FIELDS, Event, GraphUnit
from meeting_pipeline.minutes.graph_evidence import quote_anchor
from meeting_pipeline.minutes.model_runtime import ModelRuntimeError

RELATION_PROMPT = GROUNDING + (
    "Nối các ý trong events với ý trước đó ở context/events khi có quan hệ rõ ràng. "
    "Đặc biệt theo dõi đề xuất, phản đối, rút đề xuất, thay thời hạn, chấp thuận và điều kiện. "
    "Cùng chủ đề không đủ để nối. Không bắt buộc phải có quan hệ. "
    "source_quote và target_quote là đoạn con NGUYÊN VĂN trong text của hai ý. "
    "Một quyết định không có nghĩa mọi đề xuất trước đó được chấp thuận. "
    "Dùng refers_to nếu chỉ nhắc lại; supports, opposes, amends, withdraws, supersedes, "
    "accepts, depends_on khi đúng nguồn. Chỉ source trong events, target phải đứng trước source. "
    "Nếu chỉ đổi một thuộc tính, dùng amends với field là owner, deadline, condition "
    "hoặc document_version. Trích cả cụm nói rõ việc thay đổi. "
    'Trả {"relations":[{"source":"c1","target":"c0","kind":"opposes",'
    '"source_quote":"...","target_quote":"...","field":null}]}.'
)


def connect_events(
    session: Any, events: list[Event], existing: list[dict], units: list[GraphUnit]
) -> list[dict]:
    result = list(existing)
    known = set()
    units_by_id = {unit.unit_id: unit for unit in units}
    # No quadratic pair construction. Each event sees a short same-session history.
    eligible = [e for e in events if e.editorial_role == "discussion" and e.kind != "filler"]
    positions = {e.event_id: i for i, e in enumerate(events)}
    by_id = {e.event_id: e for e in events}
    anchors = OrderedDict()
    for start in range(0, len(eligible), 6):
        current = eligible[start : start + 6]
        prior = [
            e
            for e in eligible[max(0, start - 6) : start]
            if any(e.session_id == c.session_id for c in current)
        ]
        prior_ids = {event.event_id for event in prior}
        for event in current:
            key = (event.session_id, event.issue.casefold().strip())
            if not key[1]:
                continue
            for anchor in anchors.get(key, []):
                if anchor.event_id not in prior_ids and len(prior) < 10:
                    prior.append(anchor)
                    prior_ids.add(anchor.event_id)
        available = [*prior, *current]
        aliases = {e.event_id: f"c{i}" for i, e in enumerate(available)}
        reverse = {short: eid for eid, short in aliases.items()}

        def row(e, aliases=aliases):
            return {
                "id": aliases[e.event_id],
                "text": e.text,
                "kind": e.kind,
                "session": e.session_id,
            }

        context = [row(e) for e in prior]
        for batch in bounded_batches(
            session,
            [row(e) for e in current],
            RELATION_PROMPT,
            max_items=6,
            extra={"context": context},
            key="events",
        ):
            try:
                response = session.generate_json(
                    RELATION_PROMPT, {"context": context, "events": batch}
                )
                rows = response.get("relations", [])
                if not isinstance(rows, list):
                    continue
                sources = {reverse[r["id"]] for r in batch}
                visible = sources | {reverse[r["id"]] for r in context}
                for relation in rows:
                    if not isinstance(relation, dict):
                        continue
                    source = by_id.get(reverse.get(relation.get("source")))
                    target = by_id.get(reverse.get(relation.get("target")))
                    kind = relation.get("kind")
                    if (
                        not source
                        or not target
                        or source.event_id not in sources
                        or target.event_id not in visible
                        or kind not in RELATIONS
                        or source.session_id != target.session_id
                        or positions[target.event_id] >= positions[source.event_id]
                    ):
                        continue
                    a, b = relation.get("source_quote"), relation.get("target_quote")
                    if not isinstance(a, str) or not a.strip() or a not in source.text:
                        continue
                    if not isinstance(b, str) or not b.strip() or b not in target.text:
                        continue
                    field = relation.get("field")
                    if field is not None and field not in FACT_FIELDS:
                        continue
                    source_anchor = quote_anchor(units_by_id[source.unit_ids[0]], a, source.anchor)
                    target_anchor = quote_anchor(units_by_id[target.unit_ids[0]], b, target.anchor)
                    if not source_anchor or not target_anchor:
                        continue
                    key = (source.event_id, target.event_id, kind)
                    if key in known:
                        continue
                    known.add(key)
                    result.append(
                        {
                            "source": source.event_id,
                            "target": target.event_id,
                            "kind": kind,
                            "evidence_ids": list(
                                dict.fromkeys([source_anchor.unit_id, target_anchor.unit_id])
                            ),
                            "anchors": [source_anchor.model_dump(), target_anchor.model_dump()],
                            "field": field if kind == "amends" else None,
                        }
                    )
            except (ModelRuntimeError, ValueError, TypeError, KeyError):
                continue
        for event in current:
            if (
                event.kind not in {"proposal", "decision", "task", "withdrawal", "amendment"}
                or not event.issue
            ):
                continue
            key = (event.session_id, event.issue.casefold().strip())
            anchors[key] = [*anchors.get(key, []), event][-2:]
            anchors.move_to_end(key)
            if len(anchors) > 256:
                anchors.popitem(last=False)
    return result
