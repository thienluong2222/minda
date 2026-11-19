"""Plan by issue, write many-to-many paragraphs, then verify against raw sources."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

import numpy as np

from meeting_pipeline.minutes.graph_builder import GROUNDING, unit_row
from meeting_pipeline.minutes.graph_contracts import (
    INACTIVE_STATES,
    MeetingGraph,
    Paragraph,
    Section,
    StyleProfile,
    remap_identifiers,
)
from meeting_pipeline.minutes.graph_editorial import (
    STRUCTURAL_ROLES,
    adaptive_sections,
    editorial_role,
    populate_outline,
    prose_presentation,
    readable_source,
)
from meeting_pipeline.minutes.graph_values import canonical_values
from meeting_pipeline.minutes.graph_verification import (
    assertion_fragments,
    deadline_binding_risks,
    validate_alignments,
)
from meeting_pipeline.minutes.model_runtime import ModelRuntimeError
from meeting_pipeline.minutes.style_memory import scoped_instructions

WRITE_PROMPT = GROUNDING + (
    "Viết nội dung biên bản thành đoạn tự nhiên theo vấn đề từ claims và sources. "
    "Gộp nhiều lượt lời, bỏ lặp cơ học; giữ lý do quan trọng, ý kiến khác nhau, trạng thái "
    "cuối cùng, điều kiện, người nhận việc và thời hạn. Không thêm nhận định ngoài nguồn. "
    "Mỗi claim bắt buộc được thể hiện ít nhất một lần, có thể cùng một đoạn; "
    "không chỉ chép lời theo từng người. Nếu source_fallback, đọc nguồn thận trọng. "
    "Viết cô đọng, tránh giải thích dài thêm nguồn hoặc nhắc lại cùng kết luận. "
    "Không chép vai trò, dấu phân cách trong nhãn người nói vào tên. "
    "Không đổi giao việc/dự kiến thành việc đã làm. Chỉ một object JSON hợp lệ, không chú thích. "
    "Chỉ tổng hợp claims bắt buộc; sources bổ sung chỉ để hiểu, không lặp toàn cuộc họp. "
    "source_text là nội dung của claim. completed_in_source=false thì không thêm 'đã làm'. "
    "Dùng từ trạng thái sát nguồn. Giữ 'đề nghị', 'chốt', 'giao', 'đồng ý' theo đúng ý. "
    "Chỉ viết 'cam kết' nếu nguồn có chính cụm đó. "
    "evidence_ids có thể để []; hệ thống tự gắn nguồn từ claim_ids. "
    "Áp dụng style theo scope của loại ý hoặc mục. Văn phong không thay đổi sự kiện. "
    "Các trường trong claims là giá trị hiệu lực. Dùng updates và lifecycle "
    "để phân biệt lịch sử và kết luận. "
    "Khi ý có cập nhật, diễn đạt đúng giá trị hiện hành, có thể lược giá trị cũ. "
    "Theo thứ tự dàn ý. Ý optional đang chọn có thể viết ngắn, giữ đủ ý required. "
    "Mỗi câu có một ý chính. Không đánh số câu. "
    "Theo dàn ý: nối thảo luận, thay đổi và kết luận cuối cùng; không kể lại từng lượt lời. "
    "Không đưa thông tin khai mạc, thành phần hoặc kết thúc vào mọi mục. "
    "Không chép số trong nhãn 'Người lạ 1' như số liệu. Không dùng cụm rỗng "
    "như 'người thực hiện sẽ thực hiện'. Giữ cách gọi người nhất quán; tên chưa rõ thì "
    "dùng 'Người phát biểu', không đoán tên và không dùng nhãn 'Người lạ 1'. "
    "Không tự thêm số lượng bằng 'một người tham dự'. Không viết nội dung của mục khác từ context. "
    "Bỏ lời điều khiển như 'tôi xin đọc lại', 'thêm điểm nữa', 'không bổ sung gì thêm'; "
    "trình bày thẳng nội dung chính đằng sau. Không kết đoạn bằng câu hành chính rỗng. "
    'Trả {"title":"Đề mục ngắn có căn cứ","paragraphs":[{"text":"...",'
    '"claim_ids":["..."],"evidence_ids":["..."]}]}.'
)
VERIFY_PROMPT = GROUNDING + (
    "Kiểm tra từng đoạn theo sources gốc, không tin nhãn trên graph. "
    "Kiểm tra việc bỏ mất ý của claim bắt buộc và việc thêm ý không có căn cứ. "
    "Đặc biệt kiểm tra đề nghị/quyết định, chưa/đã, chủ thể, thời hạn, số liệu và điều kiện. "
    "reason tối đa 15 từ; không kể lại nội dung hoặc liệt kê ID trong reason. "
    "Mỗi phần tử paragraphs có paragraph_index; trả một check cho đúng chỉ số được cung cấp. "
    'Trả {"checks":[{"paragraph_index":0,"verdict":"supported|unsupported|uncertain",'
    '"reason":"...","missing_claim_ids":[]}]} đủ từng đoạn.'
)
ALIGNMENT_PROMPT = GROUNDING + (
    "Kiểm tra từng đoạn biên bản đối chiếu sources gốc. fragments là các câu đã đánh số từ 0. "
    "Kiểm đủ nghĩa tất cả claims và kiểm từng mệnh đề trong fragments, kể cả ý tự thêm. "
    "Đối chiếu vai trò, trạng thái, phủ định, chủ thể, số, hạn và điều kiện của từng claim. "
    "Nếu supported, assertions phải phủ đủ claim_ids và mọi fragment. "
    "Mỗi hàng chọn fragment chứa ý, claim_id của ý và evidence_ids đủ chứng minh, "
    "gồm unit đầu tiên của claim và mọi update_evidence_ids. Một fragment có thể có nhiều hàng. "
    "Nếu sai hoặc không đủ căn cứ, dùng unsupported hoặc uncertain. reason tối đa 10 từ. "
    'Trả {"checks":[{"paragraph_index":0,"verdict":"supported","reason":"",'
    '"missing_claim_ids":[],"assertions":[{"claim_id":"c0","fragment":0,'
    '"evidence_ids":["u0"]}]}]}.'
)
SINGLE_CLAIM_VERIFY = GROUNDING + (
    "Kiểm tra từng đoạn biên bản đối chiếu với sources gốc của duy nhất một claim. "
    "Đọc từng mệnh đề trong fragments. Đoạn phải giữ đủ ý, chủ thể, trạng thái, "
    "phủ định, thời hạn, điều kiện và mọi cập nhật có căn cứ. "
    "Nếu bất cứ mệnh đề nào sai, thiếu ý, hoặc ngoài nguồn của claim, không trả supported. "
    'Trả {"checks":[{"paragraph_index":0,"verdict":"supported|unsupported|uncertain",'
    '"reason":"tối đa 10 từ","missing_claim_ids":[]} ]}.'
)
COMPACT_WRITE_PROMPT = WRITE_PROMPT.split('Trả {"title"')[0] + (
    "Viết đúng MỘT đoạn thể hiện đủ các claims bắt buộc. "
    "Hệ thống quản lý claim_ids; không sinh claim_ids. "
    "Chi tiết ngữ cảnh chỉ để giải thích claim; khi dùng phải ghi evidence_ids nguồn đó. "
    "Giữ nguyên mã phòng và mã tài liệu trong nguồn, không tự đoán hoặc đổi mã. "
    'Trả {"title":"Đề mục ngắn có căn cứ","text":"Đoạn biên bản đầy đủ ý bắt buộc",'
    '"evidence_ids":[]}. Bỏ evidence_ids nếu chỉ dùng nguồn của các claims.'
)
CRITICAL = {
    "proposal",
    "objection",
    "agreement",
    "decision",
    "task",
    "withdrawal",
    "amendment",
    "vote",
    "unresolved",
}


def plan_sections(
    graph: MeetingGraph,
    *,
    use_graph: bool = True,
    soft: bool = True,
    mode: str = "general",
    information_budget: int = 0,
    editorial_layout: bool = False,
) -> tuple[list[Section], list[dict[str, Any]]]:
    positions = {u.unit_id: i for i, u in enumerate(graph.units)}
    events_by_id = {event.event_id: event for event in graph.events}
    groups: dict[int, list[str]] = {}
    ledger = []
    voted_sessions = {
        e.session_id for e in graph.events if e.editorial_role == "vote" or e.kind == "vote"
    }
    for event in graph.events:
        i = positions[event.unit_ids[0]]
        role = (
            event.editorial_role
            if event.editorial_role != "discussion"
            else editorial_role(event.text)
        )
        if (
            event.session_id in voted_sessions
            and event.kind in {"question", "proposal"}
            and re.search(r"xin biểu quyết|ai tán thành.*giơ tay", event.text, re.I)
            and not re.search(
                r"phụ trách|được giao|trước ngày|chậm nhất|kiểm tra|gửi|nhập|phân quyền",
                event.text,
                re.I,
            )
        ):
            ledger.append(
                {
                    "claim_id": event.event_id,
                    "unit_ids": event.unit_ids,
                    "disposition": "context_only",
                    "reason": "voting_procedure",
                }
            )
            continue
        if role in STRUCTURAL_ROLES:
            ledger.append(
                {
                    "claim_id": event.event_id,
                    "unit_ids": event.unit_ids,
                    "disposition": "context_only",
                    "reason": role,
                    "needs_review": role == "review",
                }
            )
            continue
        if event.kind == "filler":
            ledger.append(
                {
                    "claim_id": event.event_id,
                    "unit_ids": event.unit_ids,
                    "disposition": "filler",
                    "reason": "Lời đệm hoặc chào thuần túy.",
                }
            )
            continue
        primary = int(graph.topics["primary"][i])
        groups.setdefault(primary, []).append(event.event_id)
        ledger.append(
            {
                "claim_id": event.event_id,
                "unit_ids": event.unit_ids,
                "disposition": "included",
                "critical": event.kind in CRITICAL,
                "section_id": f"section_{primary}",
            }
        )
    sections = [
        Section(
            section_id=f"section_{topic}",
            title=graph.topics["titles"][topic],
            claim_ids=ids,
            topic_id=f"topic:{topic}",
            summary=(graph.topics.get("summaries") or [""] * graph.topics["cluster_count"])[topic],
        )
        for topic, ids in sorted(
            groups.items(),
            key=lambda pair: min(positions[events_by_id[eid].unit_ids[0]] for eid in pair[1]),
        )
    ]
    # Compress exact, same-speaker repetitions only. Semantic similarity alone
    # must never merge distinct facts, objections or state transitions.
    if use_graph:
        linked = {
            endpoint
            for edge in graph.edges
            if edge.kind not in {"contains", "next", "about", "spoken_by", "evidenced_by"}
            for endpoint in (edge.source, edge.target)
        }
        units = {u.unit_id: u for u in graph.units}
        rows_by_id = {row["claim_id"]: row for row in ledger}
        for section in sections:
            seen, selected = {}, []
            for cid in section.claim_ids:
                event = events_by_id[cid]
                unit = units[event.unit_ids[0]]
                compressible = (
                    event.kind == "information"
                    and len(event.unit_ids) == 1
                    and not re.search(
                        r"\b(?:tôi|đó|này|vậy|đồng ý|nhất trí|đề nghị|đề xuất|chưa|không)\b",
                        unit.original,
                        re.I,
                    )
                    and cid not in linked
                    and not event.owner
                    and not event.deadline
                    and not event.condition
                    and not event.document_version
                    and not event.warnings
                )
                key = (
                    event.session_id,
                    unit.episode_id,
                    unit.speaker,
                    unit.speaker_id,
                    event.lifecycle,
                    re.sub(r"\s+", " ", unit.original).strip(),
                )
                if compressible and key in seen:
                    representative = seen[key]
                    section.claim_groups.setdefault(representative, []).append(cid)
                    rows_by_id[cid].update(disposition="merged", representative=representative)
                else:
                    selected.append(cid)
                    if compressible:
                        seen[key] = cid
            if mode == "general" and information_budget:
                count = 0
                retained = []
                for cid in selected:
                    event = events_by_id[cid]
                    # Uncertain extraction, linked events and all critical kinds
                    # remain mandatory even when the presentation budget is full.
                    eligible = (
                        event.kind == "information"
                        and event.extraction == "model"
                        and not event.warnings
                        and cid not in linked
                        and not any(
                            (event.owner, event.deadline, event.condition, event.document_version)
                        )
                    )
                    if eligible:
                        count += 1
                    if eligible and count > information_budget:
                        rows_by_id[cid].update(
                            disposition="context_only", reason="presentation_budget"
                        )
                        for alias in section.claim_groups.pop(cid, []):
                            rows_by_id[alias].update(
                                disposition="context_only", reason="presentation_budget"
                            )
                    else:
                        retained.append(cid)
                selected = retained
            section.claim_ids = selected
    if editorial_layout:
        sections = adaptive_sections(graph, sections, ledger)
    populate_outline(sections, graph.events, graph.edges if use_graph else [])
    return sections, ledger


def packet_for(
    graph: MeetingGraph, claim_ids: list[str], *, use_graph: bool, soft: bool
) -> dict[str, Any]:
    events = {e.event_id: e for e in graph.events}
    unit_ids = {uid for eid in claim_ids for uid in events[eid].unit_ids}
    unit_ids.update(a.unit_id for eid in claim_ids for a in events[eid].state_evidence)
    unit_ids.update(
        update.evidence.unit_id for eid in claim_ids for update in events[eid].amendments.values()
    )
    selected = set(claim_ids)
    if use_graph:
        # The stored graph retains complete history. A bounded local context avoids
        # pulling an entire long meeting through transitive discourse references.
        frontier = set(selected)
        state_relations = {"amends", "withdraws", "supersedes", "accepts", "depends_on"}
        for _ in range(2):
            following = set()
            for edge in graph.edges:
                if edge.asserted and edge.kind in state_relations:
                    if edge.source in frontier or edge.target in frontier:
                        for endpoint in (edge.source, edge.target):
                            if endpoint in events and endpoint not in selected:
                                following.add(endpoint)
            selected.update(following)
            frontier = following
        for edge in graph.edges:
            if edge.kind in {"refers_to", "supports", "opposes"}:
                if edge.source in claim_ids and edge.target in events:
                    selected.add(edge.target)
                elif edge.target in claim_ids and edge.source in events:
                    selected.add(edge.source)
        unit_ids.update(uid for eid in selected for uid in events[eid].unit_ids)
        # Soft topic membership affects retrieval; it never establishes an event transition.
        if soft and graph.topics["cluster_count"] > 1:
            positions = {u.unit_id: i for i, u in enumerate(graph.units)}
            u = np.asarray(graph.topics["membership"])
            rows = [positions[uid] for uid in unit_ids]
            affinity = u @ u[rows].mean(axis=0)
            if "parent_membership" in graph.topics:
                parent = np.asarray(graph.topics["parent_membership"])
                affinity = 0.5 * affinity + 0.5 * (parent @ parent[rows].mean(axis=0))
            extra = [
                i for i in np.argsort(affinity)[::-1] if graph.units[i].unit_id not in unit_ids
            ][:2]
            unit_ids.update(graph.units[i].unit_id for i in extra)
    # Raw adjacent turns also remain available to graph-free paragraph baselines.
    positions = {u.unit_id: i for i, u in enumerate(graph.units)}
    for i in [positions[uid] for uid in list(unit_ids)]:
        if i and graph.units[i - 1].session_id == graph.units[i].session_id:
            unit_ids.add(graph.units[i - 1].unit_id)
    claims = []
    for eid in claim_ids:
        event = events[eid]
        claims.append(
            {
                "claim_id": eid,
                "source_text": event.text,
                "unit_ids": event.unit_ids,
                "kind": event.kind,
                "lifecycle": event.lifecycle,
                "owner": event.current_value("owner"),
                "deadline": event.current_value("deadline"),
                "condition": event.current_value("condition"),
                "document_version": event.current_value("document_version"),
                "updates": {
                    field: update.evidence.quote for field, update in event.amendments.items()
                },
                "update_evidence_ids": list(
                    dict.fromkeys(update.evidence.unit_id for update in event.amendments.values())
                ),
                "state_evidence_ids": list(dict.fromkeys(a.unit_id for a in event.state_evidence)),
                "extraction": event.extraction,
                "completed_in_source": bool(re.search(r"\bđã\b", event.text, re.I))
                and not bool(re.search(r"\b(?:chưa|nếu|dự kiến)\b", event.text, re.I)),
            }
        )
    return {
        "state_context_hops": 2 if use_graph else 0,
        "require_alignments": graph.schema_version == "2.0",
        "claims": claims,
        "sources": [unit_row(unit, raw=True) for unit in graph.units if unit.unit_id in unit_ids],
        "relations": [
            edge.model_dump(exclude={"anchors"}, exclude_none=True)
            for edge in graph.edges
            if use_graph
            and edge.source in selected
            and edge.target in selected
            and edge.kind not in {"contains", "about", "next"}
        ],
    }


def numeric_values(text: str) -> Counter:
    # Associate exact numbers with the paragraph's cited source, not the full meeting.
    return Counter(re.findall(r"\d+(?:[.,:/-]\d+)*", text))


def writing_packet(graph: MeetingGraph, packet: dict, claim_ids: list[str]) -> dict:
    """Generation sees selected facts. Broader context is reserved for verification."""
    required = set(claim_ids)
    by_unit = {}
    for event in graph.events:
        if event.event_id in required:
            by_unit.setdefault(event.unit_ids[0], []).append(event.text)
    source_rows = {row["unit_id"]: row for row in packet["sources"]}
    return {
        "claims": packet["claims"],
        "sources": [{"unit_id": uid, "speaker": source_rows[uid]["speaker"]} for uid in by_unit],
        "relations": [
            edge
            for edge in packet["relations"]
            if edge["asserted"] and edge["source"] in required and edge["target"] in required
        ],
    }


def state_evidence(graph: MeetingGraph, claim_ids: list[str]) -> set[str]:
    return {
        a.unit_id
        for event in graph.events
        if event.event_id in claim_ids
        for a in event.state_evidence
    } | {
        uid
        for edge in graph.edges
        if edge.asserted
        and edge.kind in {"amends", "withdraws", "supersedes", "accepts", "depends_on"}
        and (edge.source in claim_ids or edge.target in claim_ids)
        for uid in edge.evidence_ids
    }


def aliased_request(session: Any, system: str, payload: dict[str, Any]) -> dict[str, Any]:
    source_ids = [row["unit_id"] for row in payload.get("sources", [])]
    claim_ids = [row["claim_id"] for row in payload.get("claims", [])]
    for relation in payload.get("relations", []):
        claim_ids.extend([relation["source"], relation["target"]])
    aliases = {uid: f"u{i}" for i, uid in enumerate(dict.fromkeys(source_ids))}
    aliases.update({cid: f"c{i}" for i, cid in enumerate(dict.fromkeys(claim_ids))})
    response = session.generate_json(system, remap_identifiers(payload, aliases))
    return remap_identifiers(response, {short: identifier for identifier, short in aliases.items()})


def affirmed_decision(source: str, cue: str) -> bool:
    """Adding past aspect is compatible with an explicitly affirmed decision.

    Proposals, negation and conditional decisions do not establish this state.
    This lexical gate remains conservative and is not a semantic entailment model.
    """
    for clause in re.split(r"[.;!?\n]+", source.casefold()):
        for match in re.finditer(rf"\b{re.escape(cue)}\b", clause):
            prefix = clause[: match.start()]
            if re.search(r"\b(?:nếu|chỉ khi|trừ khi|giả sử)\b", clause):
                continue
            if re.search(
                r"\b(?:không|chưa|đừng|chẳng|đề nghị|đề xuất|kiến nghị|cần|nên|sẽ|"
                r"mong|muốn|dự kiến|có thể)\b",
                prefix,
            ):
                continue
            return True
    return False


def deterministic_risks(text: str, source: str) -> list[str]:
    risks = []
    # Diarisation labels are identifiers, not numeric facts in the meeting.
    text = re.sub(r"\b(?:Người lạ|Speaker)\s+\d+\b", "người tham dự", text, flags=re.I)
    source = re.sub(r"\b(?:Người lạ|Speaker)\s+\d+\b", "người tham dự", source, flags=re.I)
    source_vals = canonical_values(source)
    if canonical_values(text) - source_vals:
        risks.append("introduced_or_duplicated_numeric_value")
    if any(key[0] == "date" for key in source_vals) and re.search(
        r"\bngày\s+tháng\b", text, re.I
    ):
        risks.append("dropped_date_day")
    lower_text = text.casefold()
    lower_source = source.casefold()
    for match in re.finditer(
        r"\b(?:mỗi|hằng|hàng)\s+(?:ngày|tuần|tháng|năm)\b", lower_text
    ):
        cue = match.group(0)
        if cue not in lower_source:
            risks.append("introduced_recurrence:" + cue)
            break
    if re.search(r"\bphản bác\b", text, re.I) and not re.search(
        r"\b(?:phản bác|phản đối|bác bỏ|không đồng ý)\b", source, re.I
    ):
        risks.append("unsupported_objection")
    for marker in ("đã hoàn thành", "đã thống nhất", "đã thông qua", "cam kết"):
        if marker in lower_text and marker not in lower_source:
            if marker in {"đã thống nhất", "đã thông qua"} and affirmed_decision(
                source, marker[3:]
            ):
                continue
            risks.append("introduced_state:" + marker)
    return risks


def completion_risks(text: str, rows: list[dict[str, Any]]) -> list[str]:
    """Check actor-action completion even when another actor already did something."""
    names = {row["speaker"] for row in rows if row.get("speaker")}
    source = " ".join(
        row["speaker"] + ": " + re.sub(r"\btôi\b", row["speaker"], row["text"], flags=re.I)
        for row in rows
    )
    actions = r"gửi|nộp|nhập|rà soát|kiểm tra|hoàn thành|thực hiện|sản xuất|đặt|phác|tách"
    risks = []
    for name in names:
        pattern = re.compile(
            rf"\b{re.escape(name)}\b\s*[:,]?\s+(?:(?:cũng|đều|vừa|mới)\s+){{0,3}}đã\s+({actions})\b",
            re.I,
        )
        existing = {m.group(1).casefold() for m in pattern.finditer(source)}
        introduced = {m.group(1).casefold() for m in pattern.finditer(text)} - existing
        if introduced:
            risks.extend(
                "unsupported_actor_completion:" + name + ":" + action for action in introduced
            )
    return risks


def verify_paragraphs(
    session: Any, paragraphs: list[Paragraph], packet: dict[str, Any]
) -> list[dict[str, Any]]:
    source_by_id = {row["unit_id"]: row["text"] for row in packet["sources"]}
    claims = {row["claim_id"]: row for row in packet.get("claims", [])}
    require_alignments = packet.get("require_alignments", False)
    checks = []
    for i, paragraph in enumerate(paragraphs):
        paragraph.alignments = []
        source = " ".join(
            source_by_id[uid] for uid in paragraph.evidence_ids if uid in source_by_id
        )
        checks.append(
            {
                "paragraph_index": i,
                "risks": deterministic_risks(paragraph.text, source)
                + completion_risks(
                    paragraph.text,
                    [row for row in packet["sources"] if row["unit_id"] in paragraph.evidence_ids],
                )
                + deadline_binding_risks(
                    paragraph.text, [claims[cid] for cid in paragraph.claim_ids if cid in claims]
                ),
            }
        )
    pending = [c["paragraph_index"] for c in checks if not c["risks"]]
    for paragraph, check in zip(paragraphs, checks, strict=True):
        source = " ".join(
            source_by_id[uid] for uid in paragraph.evidence_ids if uid in source_by_id
        )
        extra_values = canonical_values(paragraph.text) - canonical_values(source)
        if extra_values:
            check["numeric_conflicts"] = [
                {"value": value, "extra_count": count}
                for value, count in list(extra_values.items())[:8]
            ]
    for check in checks:
        if check["risks"]:
            check.update(verdict="deterministic_rejected", reason="; ".join(check["risks"]))
    if not pending:
        return checks
    direct_claim = next(iter(claims.values())) if require_alignments and len(claims) == 1 else None
    verification_packet = packet
    if direct_claim:
        direct_ids = set(
            [
                *direct_claim["unit_ids"],
                *direct_claim["update_evidence_ids"],
                *direct_claim["state_evidence_ids"],
            ]
        )
        verification_packet = {
            **packet,
            "sources": [row for row in packet["sources"] if row["unit_id"] in direct_ids],
        }
    prompt = VERIFY_PROMPT
    if require_alignments:
        prompt = SINGLE_CLAIM_VERIFY if direct_claim else ALIGNMENT_PROMPT
    try:
        response = aliased_request(
            session,
            prompt,
            {
                **verification_packet,
                "paragraphs": [
                    {
                        "paragraph_index": i,
                        "claim_ids": paragraphs[i].claim_ids,
                        "evidence_ids": paragraphs[i].evidence_ids,
                        **(
                            {
                                "fragments": [
                                    m.group().strip()
                                    for m in assertion_fragments(paragraphs[i].text)
                                ]
                            }
                            if require_alignments
                            else {"text": paragraphs[i].text}
                        ),
                    }
                    for i in pending
                ],
            },
        )
        rows = response.get("checks", [])
        by_index = {int(row["paragraph_index"]): row for row in rows}
        if len(by_index) != len(rows) or set(by_index) != set(pending):
            raise ValueError("Kiểm tra thiếu hoặc trùng đoạn.")
        for check in checks:
            if check["paragraph_index"] not in pending:
                continue
            result = by_index[check["paragraph_index"]]
            check.update(
                verdict=result.get("verdict"),
                reason=str(result.get("reason", "")),
                missing_claim_ids=result.get("missing_claim_ids", []),
            )
            if result.get("verdict") != "supported" or result.get("missing_claim_ids"):
                check["risks"].append("semantic_check_not_supported")
            elif require_alignments:
                paragraph = paragraphs[check["paragraph_index"]]
                assertions = result.get("assertions")
                if direct_claim:
                    evidence_ids = [row["unit_id"] for row in verification_packet["sources"]]
                    assertions = [
                        {
                            "claim_id": direct_claim["claim_id"],
                            "fragment": index,
                            "evidence_ids": evidence_ids,
                        }
                        for index, _ in enumerate(assertion_fragments(paragraph.text))
                    ]
                alignments, risks = validate_alignments(
                    paragraph, assertions, claims, set(source_by_id)
                )
                check["risks"].extend(risks)
                if not risks:
                    paragraph.alignments = alignments
                    check["aligned_claim_ids"] = sorted({item.claim_id for item in alignments})
                    check["alignment_method"] = "single_claim" if direct_claim else "model"
    except (ModelRuntimeError, ValueError, TypeError, KeyError) as exc:
        for check in checks:
            if check["paragraph_index"] not in pending:
                continue
            check.update(verdict="uncertain", reason=str(exc))
            check["risks"].append("verification_unavailable")
    return checks


def repair_sentences(
    session: Any, paragraphs: list[Paragraph], packet: dict
) -> list[Paragraph] | None:
    sources = {row["unit_id"]: row["text"] for row in packet["sources"]}
    split, problems = [], []
    for index, paragraph in enumerate(paragraphs):
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-ZÀ-Ỹ])|\n+", paragraph.text)
        split.append(sentences)
        source = " ".join(sources[uid] for uid in paragraph.evidence_ids if uid in sources)
        for position, sentence in enumerate(sentences):
            risks = deterministic_risks(sentence, source)
            if risks:
                problems.append(
                    {
                        "paragraph_index": index,
                        "sentence_index": position,
                        "text": sentence,
                        "risks": risks,
                        "sources": source,
                    }
                )
    if not problems:
        return None
    prompt = GROUNDING + (
        "Chỉ sửa các câu được liệt kê. Giữ ý, người, thời hạn, điều kiện theo nguồn. "
        "Sửa mã phòng sai từ nguồn chính xác, không thay các câu khác. Không thêm mở đầu/kết luận. "
        'Trả {"patches":[{"paragraph_index":0,"sentence_index":0,"text":"câu đã sửa"}]}.'
    )
    try:
        response = session.generate_json(prompt, {"sentences": problems})
        expected = {(p["paragraph_index"], p["sentence_index"]) for p in problems}
        patches = response.get("patches", [])
        actual = {(p["paragraph_index"], p["sentence_index"]) for p in patches}
        if len(patches) != len(expected) or actual != expected:
            return None
        for patch in patches:
            text = patch["text"]
            if not isinstance(text, str) or not text.strip():
                return None
            split[patch["paragraph_index"]][patch["sentence_index"]] = text.strip()
        return [
            p.model_copy(update={"text": " ".join(sentences)})
            for p, sentences in zip(paragraphs, split, strict=True)
        ]
    except (ModelRuntimeError, ValueError, TypeError, KeyError, IndexError):
        return None


def event_source_text(event, units, events) -> str:
    unit = units[event.unit_ids[0]]
    use_corrected = unit.text != unit.original and (
        not event.anchor
        or event.anchor.quote.strip() == unit.original.strip()
        or sum(1 for row in events.values() if row.unit_ids and row.unit_ids[0] == unit.unit_id)
        == 1
    )
    raw_quote = unit.text if use_corrected else (event.anchor.quote if event.anchor else unit.text)
    text = readable_source(raw_quote, unit.speaker)
    if event.lifecycle in INACTIVE_STATES:
        prefix = (
            "Nội dung đã rút. " if event.lifecycle == "withdrawn" else "Nội dung đã được thay thế. "
        )
        return prefix + text
    if event.amendments:
        revisions = dict.fromkeys(update.source_event_id for update in event.amendments.values())
        changes = [
            readable_source(change.anchor.quote if change.anchor else change.text)
            for event_id in revisions
            if (change := events.get(event_id))
        ]
        return "Nội dung ban đầu. " + text + " Điều chỉnh sau đó. " + " ".join(changes)
    return text


def source_paragraphs(graph: MeetingGraph, claim_ids: list[str]) -> list[Paragraph]:
    by_id = {e.event_id: e for e in graph.events}
    units = {unit.unit_id: unit for unit in graph.units}
    fragments = [event_source_text(by_id[eid], units, by_id) for eid in claim_ids]
    # Explicit per-section source fallback; never masquerades as successful abstraction.
    return [
        Paragraph(
            text=" ".join(dict.fromkeys(fragment for fragment in fragments if fragment)),
            claim_ids=claim_ids,
            evidence_ids=list(
                dict.fromkeys(
                    [
                        *(uid for eid in claim_ids for uid in by_id[eid].unit_ids),
                        *sorted(state_evidence(graph, claim_ids)),
                    ]
                )
            ),
            verification="source_fallback",
        )
    ]


def finalize_graph_sections(graph: MeetingGraph, sections: list[Section]) -> list[Section]:
    """Deterministic presentation after all model requests, safe to replay from stored results."""
    defaults = {f"section_{i}": title for i, title in enumerate(graph.topics.get("titles", []))}
    for section in sections:
        if section.title.casefold().strip(" .…") in {"đề mục ngắn có căn cứ", "", "tiêu đề"}:
            section.title = defaults.get(section.section_id, "Nội dung cuộc họp")
        section.paragraphs = [
            source_paragraphs(graph, paragraph.claim_ids)[0]
            if paragraph.verification == "source_fallback"
            else paragraph
            for paragraph in section.paragraphs
        ]
    return sections


def polish_sections(
    session: Any,
    graph: MeetingGraph,
    sections: list[Section],
    style: StyleProfile,
    *,
    verify: bool = True,
    use_graph: bool = True,
    soft: bool = True,
) -> list[dict]:
    """A failed style pass never discards already accepted text or its citations."""
    audit = []
    for section in sections:
        if len(section.paragraphs) < 2:
            continue
        packet = packet_for(graph, section.claim_ids, use_graph=use_graph, soft=soft)
        payload = {
            **writing_packet(graph, packet, section.claim_ids),
            "section_title": section.title,
            "draft": [p.model_dump() for p in section.paragraphs],
            "outline": [
                {
                    "claim_ids": item.claim_ids,
                    "role": item.role,
                    "lifecycle": item.lifecycle,
                    "priority": item.priority,
                }
                for item in section.outline
                if item.included
            ],
            "style": scoped_instructions(
                style, section.section_id, {row["kind"] for row in packet["claims"]}
            ),
        }
        prompt = WRITE_PROMPT + (
            "Đây là lượt biên tập cuối cho các đoạn đã kiểm tra. Nối ý, giảm lặp, "
            "giữ điều kiện và trạng thái cuối; không thêm thông tin từ ngữ cảnh. "
            "Giữ đủ các claim bắt buộc, mỗi claim một lần trong nội dung. "
            "Trả paragraphs theo schema, không trả một chuỗi text duy nhất."
        )
        if (
            session.token_count(prompt + str(payload))
            > session.settings.input_token_budget - session.settings.output_token_budget - 650
        ):
            audit.append(
                {
                    "section_id": section.section_id,
                    "action": "polish_kept_draft",
                    "reason": "bounded_context",
                }
            )
            continue
        try:
            response = aliased_request(session, prompt, payload)
            paragraphs = [Paragraph.model_validate(p) for p in response.get("paragraphs", [])]
            for paragraph in paragraphs:
                paragraph.text = prose_presentation(paragraph.text)
            if not paragraphs or {cid for p in paragraphs for cid in p.claim_ids} != set(
                section.claim_ids
            ):
                raise ValueError("Biên tập thiếu/thừa ý.")
            events = {e.event_id: e for e in graph.events}
            allowed = {r["unit_id"] for r in packet["sources"]}
            for paragraph in paragraphs:
                if (
                    not paragraph.text.strip()
                    or not paragraph.claim_ids
                    or set(paragraph.evidence_ids) - allowed
                ):
                    raise ValueError("Biên tập không có căn cứ hợp lệ.")
                paragraph.evidence_ids = list(
                    dict.fromkeys(
                        [
                            *paragraph.evidence_ids,
                            *(uid for cid in paragraph.claim_ids for uid in events[cid].unit_ids),
                            *sorted(state_evidence(graph, paragraph.claim_ids)),
                        ]
                    )
                )
            checks = verify_paragraphs(session, paragraphs, packet) if verify else []
            if not verify or any(check["risks"] for check in checks):
                raise ValueError("Bản biên tập chưa vượt qua kiểm tra nguồn.")
            for paragraph in paragraphs:
                paragraph.verification = "checked"
            section.paragraphs = paragraphs
            audit.append(
                {"section_id": section.section_id, "action": "polish_accepted", "checks": checks}
            )
        except (ModelRuntimeError, ValueError, TypeError, KeyError) as exc:
            audit.append(
                {
                    "section_id": section.section_id,
                    "action": "polish_kept_draft",
                    "reason": str(exc),
                }
            )
    return audit


def write_sections(
    session: Any,
    graph: MeetingGraph,
    sections: list[Section],
    *,
    use_graph: bool = True,
    soft: bool = True,
    style: StyleProfile | None = None,
    verify: bool = True,
    checkpoint: Any = None,
) -> tuple[list[Section], list[dict[str, Any]]]:
    audit = []
    feedback = {}
    compact = getattr(session.settings, "compact_graph_output", False)
    prompt = COMPACT_WRITE_PROMPT if compact else WRITE_PROMPT
    batch_size = getattr(session.settings, "writer_batch_size", 8)
    for section in sections:
        outline_ids = (
            [item.item_id for item in section.outline if item.included]
            if section.outline
            else []
        )
        # Honor direct section.claim_ids overrides when outline wasn't synced.
        claim_source = (
            outline_ids
            if section.outline and set(outline_ids) == set(section.claim_ids)
            else section.claim_ids
        )
        rows = [{"claim_id": cid} for cid in claim_source]
        # Bound both generation and verification inputs. A source unit is never truncated.
        batches = [rows[i : i + batch_size] for i in range(0, len(rows), batch_size)]
        pending = [([r["claim_id"] for r in batch]) for batch in batches]
        while pending:
            claim_ids = pending.pop(0)
            packet = packet_for(graph, claim_ids, use_graph=use_graph, soft=soft)
            payload = {
                **writing_packet(graph, packet, claim_ids),
                "section_title": section.title,
                "style": scoped_instructions(
                    style, section.section_id, {row["kind"] for row in packet["claims"]}
                ),
                "outline": [
                    {
                        "claim_ids": item.claim_ids,
                        "role": item.role,
                        "lifecycle": item.lifecycle,
                        "priority": item.priority,
                    }
                    for item in section.outline
                    if item.included and item.item_id in claim_ids
                ],
                "previous_text": section.paragraphs[-1].text[-240:]
                if section.paragraphs and section.paragraphs[-1].verification == "checked"
                else "",
            }
            key = tuple(claim_ids)
            if key in feedback:
                payload["revision_feedback"] = feedback[key]
            size = session.token_count(prompt + str(payload))
            # Verification repeats generated text: reserve a full output budget.
            limit = session.settings.input_token_budget - session.settings.output_token_budget - 650
            if size > limit and len(claim_ids) > 1:
                half = len(claim_ids) // 2
                pending[:0] = [claim_ids[:half], claim_ids[half:]]
                continue
            try:
                if size > session.settings.input_token_budget - 400:
                    raise ModelRuntimeError("Chuỗi căn cứ quá lớn; giữ nguồn và ghi cần rà soát.")
                result = aliased_request(session, prompt, payload)
                if compact and isinstance(result.get("text"), str):
                    # IDs come from the plan, while semantic verification still checks
                    # every required claim against the generated text and raw evidence.
                    result["paragraphs"] = [
                        {
                            "text": result["text"],
                            "claim_ids": claim_ids,
                            "evidence_ids": result.get("evidence_ids", []),
                        }
                    ]
                paragraphs = [Paragraph.model_validate(p) for p in result.get("paragraphs", [])]
                for paragraph in paragraphs:
                    paragraph.text = prose_presentation(paragraph.text)
                required = set(claim_ids)
                covered = {cid for p in paragraphs for cid in p.claim_ids}
                allowed = {row["unit_id"] for row in packet["sources"]}
                if not paragraphs or covered != required:
                    raise ValueError("Bản viết thiếu/thừa claim_id.")
                for p in paragraphs:
                    if not p.text.strip() or not p.claim_ids or set(p.evidence_ids) - allowed:
                        raise ValueError("Đoạn văn thiếu nội dung hoặc căn cứ hợp lệ.")
                    event_by_id = {e.event_id: e for e in graph.events}
                    supporting = {uid for cid in p.claim_ids for uid in event_by_id[cid].unit_ids}
                    supporting.update(state_evidence(graph, p.claim_ids))
                    p.evidence_ids = list(dict.fromkeys([*p.evidence_ids, *sorted(supporting)]))
                checks = (
                    verify_paragraphs(session, paragraphs, packet)
                    if verify
                    else [
                        {
                            "paragraph_index": i,
                            "risks": deterministic_risks(
                                p.text,
                                " ".join(
                                    row["text"]
                                    for row in packet["sources"]
                                    if row["unit_id"] in p.evidence_ids
                                ),
                            ),
                            "verdict": "not_semantically_checked",
                        }
                        for i, p in enumerate(paragraphs)
                    ]
                )
                rejected = [check for check in checks if check["risks"]]
                if rejected:
                    # Repair only offending sentences before replacing an otherwise good
                    # paragraph. The complete result still passes the existing verifier.
                    if key not in feedback and any(
                        check.get("numeric_conflicts") for check in rejected
                    ):
                        repaired = repair_sentences(session, paragraphs, packet)
                        if repaired is not None:
                            paragraphs = repaired
                            checks = (
                                verify_paragraphs(session, paragraphs, packet) if verify else checks
                            )
                            rejected = [check for check in checks if check["risks"]]
                            audit.append(
                                {
                                    "section_id": section.section_id,
                                    "claim_ids": claim_ids,
                                    "action": "sentence_repair",
                                    "checks": checks,
                                }
                            )
                if rejected:
                    retry = key not in feedback
                    audit.append(
                        {
                            "section_id": section.section_id,
                            "claim_ids": claim_ids,
                            "action": "retry" if retry else "source_fallback",
                            "checks": checks,
                            "rejected_paragraphs": [p.model_dump() for p in paragraphs],
                        }
                    )
                    if retry:
                        feedback[key] = {
                            "instruction": (
                                "Viết lại từ nguồn, sửa các lỗi đã nêu; "
                                "giữ đúng trạng thái và đủ claim."
                            ),
                            "problems": [
                                {
                                    "risks": c["risks"],
                                    "reason": c.get("reason", "")[:180],
                                    "numeric_conflicts": c.get("numeric_conflicts", []),
                                }
                                for c in rejected
                            ],
                            "previous_paragraphs": [p.model_dump() for p in paragraphs],
                            "state_instruction": (
                                "Giữ nguyên người thực hiện. Nếu bị báo "
                                "unsupported_actor_completion thì nguồn chưa xác nhận đã làm; "
                                "diễn đạt đúng nhiệm vụ dự kiến, không đổi người để né lỗi."
                            ),
                        }
                        pending.insert(0, claim_ids)
                        if checkpoint:
                            checkpoint(sections, audit)
                        continue
                    if len(claim_ids) > 1:
                        middle = len(claim_ids) // 2
                        pending[:0] = [claim_ids[:middle], claim_ids[middle:]]
                        for part in pending[:2]:
                            feedback[tuple(part)] = {
                                "instruction": (
                                    "Viết đúng các ý trong lô này. "
                                    "Giữ nguyên số, tên và từ chỉ trạng thái theo nguồn."
                                )
                            }
                        audit[-1]["action"] = "split_rejected_batch"
                        continue
                    paragraphs = source_paragraphs(graph, claim_ids)
                else:
                    for p in paragraphs:
                        p.verification = "checked" if verify else "needs_review"
                    audit.append(
                        {
                            "section_id": section.section_id,
                            "claim_ids": claim_ids,
                            "action": "accepted",
                            "checks": checks,
                        }
                    )
                    title = str(result.get("title", "")).strip()
                    title_source = " ".join(row["text"] for row in packet["sources"])
                    if (
                        title
                        and not section.title_edited
                        and not deterministic_risks(title, title_source)
                        and section.title.startswith(("Vấn đề ", "Nội dung phát sinh"))
                    ):
                        section.title = re.sub(r"[\r\n]+", " ", title)[:120]
                for paragraph in paragraphs:
                    aliases = [
                        alias
                        for cid in paragraph.claim_ids
                        for alias in section.claim_groups.get(cid, [])
                    ]
                    paragraph.claim_ids.extend(aliases)
                    event_by_id = {e.event_id: e for e in graph.events}
                    # Exact repetitions were already proven equivalent by the planner.
                    paragraph.alignments.extend(
                        [
                            alignment.model_copy(
                                update={
                                    "claim_id": alias,
                                    "evidence_ids": event_by_id[alias].unit_ids,
                                }
                            )
                            for alignment in paragraph.alignments
                            for alias in section.claim_groups.get(alignment.claim_id, [])
                        ]
                    )
                    paragraph.evidence_ids = list(
                        dict.fromkeys(
                            [
                                *paragraph.evidence_ids,
                                *(
                                    uid
                                    for alignment in paragraph.alignments
                                    for uid in alignment.evidence_ids
                                ),
                                *(uid for cid in aliases for uid in event_by_id[cid].unit_ids),
                            ]
                        )
                    )
                section.paragraphs.extend(paragraphs)
            except (ModelRuntimeError, ValueError, TypeError, KeyError) as exc:
                if key not in feedback:
                    feedback[key] = {
                        "instruction": (
                            "Trả đúng một JSON theo schema, đủ claim_ids; không chú thích."
                        ),
                        "previous_error": str(exc)[:200],
                    }
                    audit.append(
                        {
                            "section_id": section.section_id,
                            "claim_ids": claim_ids,
                            "action": "retry",
                            "reason": str(exc),
                        }
                    )
                    pending.insert(0, claim_ids)
                    if checkpoint:
                        checkpoint(sections, audit)
                    continue
                expanded = [
                    cid
                    for representative in claim_ids
                    for cid in [representative, *section.claim_groups.get(representative, [])]
                ]
                section.paragraphs.extend(source_paragraphs(graph, expanded))
                audit.append(
                    {
                        "section_id": section.section_id,
                        "claim_ids": claim_ids,
                        "action": "source_fallback",
                        "reason": str(exc),
                    }
                )
            if checkpoint:
                checkpoint(sections, audit)
    return sections, audit
