"""Fact extraction and evidence grounding for meeting minutes
(M2 rules and M3 summarization adapter).

Specification: Section 5 (F3) of docs/PLAN_BIEU_MAU_BIEN_BAN_V1.md.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.request
from typing import Any

from meeting_pipeline.domain.speaker_identity import normalize_speaker_label, person_identity_key
from meeting_pipeline.minutes.evidence_retrieval import (
    IndexedTurn,
    TurnSearchIndex,
    retrieve_evidence_for_field,
)
from meeting_pipeline.minutes.schemas import (
    EvidenceRef,
    FactStatus,
    MeetingFact,
    SemanticFieldType,
    TemplateSchema,
)

logger = logging.getLogger(__name__)


def _person_turn_groups(turns: list[IndexedTurn]) -> list[list[IndexedTurn]]:
    groups: dict[tuple[str, str], list[IndexedTurn]] = {}
    for turn in sorted(turns, key=lambda t: (t.start_sec, t.end_sec)):
        key = person_identity_key(
            turn.speaker_label,
            turn.speaker_id,
            turn.meeting_speaker_id,
            turn.speaker_status,
            turn.speaker_count,
            turn.overlap_group_id,
        )
        if key is not None:
            groups.setdefault(key, []).append(turn)
    return list(groups.values())


def _person_evidence(turn: IndexedTurn, run_id: str) -> EvidenceRef:
    return EvidenceRef(
        run_id=run_id,
        turn_id=turn.turn_id,
        source_id=turn.source_id,
        start_sec=turn.start_sec,
        end_sec=turn.end_sec,
        clip_path=turn.clip_path,
        source_kind="transcript",
        text_snippet=turn.text or f"Người nói: {turn.speaker_label}",
        confidence=None,
    )


def _explicit_role(
    turns: list[IndexedTurn],
    groups: list[list[IndexedTurn]],
    role: str,
    run_id: str,
) -> tuple[str | None, FactStatus, list[EvidenceRef], str | None]:
    """Require an explicit role statement rather than alphabetical speaker order."""
    candidates: dict[tuple[str, str], tuple[str, list[EvidenceRef]]] = {}
    for turn in turns:
        if turn.speaker_count != 1 or turn.overlap_group_id or turn.asr_status != "transcribed":
            continue
        text = normalize_speaker_label(turn.text).casefold()
        if any(word in text for word in ("đề xuất", "đề nghị", "chưa chốt", "chưa phân công")):
            continue
        if re.search(rf"\b(?:không|chưa)\b[^.!?;]{{0,60}}\b(?:{role})\b", text):
            continue
        for group in groups:
            representative = group[-1]
            name = normalize_speaker_label(representative.speaker_label)
            if representative.speaker_status == "anonymous" or name.casefold().startswith(
                ("người lạ", "speaker ")
            ):
                continue
            names = {normalize_speaker_label(t.speaker_label).casefold() for t in group}
            mentioned = any(
                re.search(rf"\b{re.escape(alias)}\s+(?:(?:là|làm)\s+)?(?:{role})\b", text)
                or re.search(
                    rf"\b(?:{role})\s*(?::|là|do)?\s*(?:(?:anh|chị|ông|bà)\s+)?"
                    rf"{re.escape(alias)}\b",
                    text,
                )
                for alias in names
            )
            key = person_identity_key(
                representative.speaker_label,
                representative.speaker_id,
                representative.meeting_speaker_id,
                representative.speaker_status,
            )
            own_key = person_identity_key(
                turn.speaker_label,
                turn.speaker_id,
                turn.meeting_speaker_id,
                turn.speaker_status,
                turn.speaker_count,
                turn.overlap_group_id,
            )
            self_role = key == own_key and re.search(
                rf"\btôi\s+(?:(?:là|làm)\s+)?(?:{role})\b",
                text,
            )
            if key is not None and (mentioned or self_role):
                if key not in candidates:
                    candidates[key] = name, []
                candidates[key][1].append(_person_evidence(turn, run_id))
    if len(candidates) == 1:
        name, evidence = next(iter(candidates.values()))
        return name, FactStatus.SUPPORTED, evidence, "Vai trò được nêu rõ trong transcript"
    if candidates:
        evidence = [ref for _, refs in candidates.values() for ref in refs]
        return None, FactStatus.CONFLICTING, evidence, "Có nhiều người được gán cùng vai trò"
    return None, FactStatus.UNKNOWN, [], "Không có thông tin phân công vai trò rõ ràng"


DECISION_KEYWORDS = [
    "thống nhất",
    "quyết định",
    "kết luận",
    "đồng ý",
    "chốt",
    "thông qua",
]

PROPOSAL_DISQUALIFIERS = [
    "tôi đề xuất",
    "hay là",
    "thử xem",
    "chưa chắc",
    "đang phân vân",
]

HOURS_ORDERED: list[tuple[str, int]] = [
    ("mười hai", 12),
    ("mười một", 11),
    ("hai mươi", 20),
    ("mười chín", 19),
    ("mười tám", 18),
    ("mười bảy", 17),
    ("mười sáu", 16),
    ("mười lăm", 15),
    ("mười bốn", 14),
    ("mười ba", 13),
    ("mười", 10),
    ("chín", 9),
    ("tám", 8),
    ("bảy", 7),
    ("sáu", 6),
    ("năm", 5),
    ("bốn", 4),
    ("ba", 3),
    ("hai", 2),
    ("một", 1),
]

MINUTES_MAP: dict[str, int] = {
    "bốn mươi lăm": 45,
    "ba mươi": 30,
    "mười lăm": 15,
    "rưỡi": 30,
}


def _extract_time_expression(text: str, prefer: str = "start") -> str | None:
    """Extract standard HH:MM time string from Vietnamese text with start/end preference."""
    t_lower = text.lower()
    found: list[tuple[int, str]] = []

    # 1. Digital e.g. 14:30 or 14h30
    for m in re.finditer(r"(\d{1,2})[:h](\d{2})", t_lower):
        found.append((m.start(), f"{int(m.group(1)):02d}:{m.group(2)}"))

    # 2. Text hours
    matched_spans: set[int] = set()
    for h_name, h_val in HOURS_ORDERED:
        pattern = rf"\b{h_name}\s*giờ(?:\s*(rưỡi|ba mươi|mười lăm|bốn mươi lăm|\d{{1,2}}))?\b"
        for m in re.finditer(pattern, t_lower):
            if any(i in matched_spans for i in range(m.start(), m.end())):
                continue
            for i in range(m.start(), m.end()):
                matched_spans.add(i)

            mins = 0
            if m.group(1):
                min_str = m.group(1).strip()
                if min_str in MINUTES_MAP:
                    mins = MINUTES_MAP[min_str]
                elif min_str.isdigit():
                    mins = int(min_str)

            actual_hour = h_val
            # If 1-6 o'clock in context, assume afternoon/evening (13:00-18:00)
            if actual_hour <= 6:
                actual_hour += 12

            found.append((m.start(), f"{actual_hour:02d}:{mins:02d}"))

    if not found:
        return None

    found_by_val = sorted([t[1] for t in found])
    return found_by_val[-1] if prefer == "end" else found_by_val[0]


class M2RuleFactExtractor:
    """Extracts factual values with evidence references using domain heuristics."""

    def extract_facts(
        self,
        schema: TemplateSchema,
        turns: list[IndexedTurn],
        meeting_metadata: dict[str, Any] | None = None,
        run_id: str = "run-1",
    ) -> list[MeetingFact]:
        """Extract facts for all fields in schema against timeline turns and metadata."""
        meta = meeting_metadata or {}
        index = TurnSearchIndex(turns)
        facts: list[MeetingFact] = []

        person_groups = _person_turn_groups(turns)

        for field in schema.fields:
            val: Any = None
            status = FactStatus.UNKNOWN
            evidence: list[EvidenceRef] = []
            reason: str | None = None
            conf: float | None = None

            st = field.semantic_type

            # Check meeting_metadata overrides first
            meta_key = field.field_id
            if meta.get(meta_key):
                val = meta[meta_key]
                status = FactStatus.SUPPORTED
                evidence.append(
                    EvidenceRef(
                        run_id=run_id,
                        turn_id="metadata",
                        source_id="metadata",
                        source_kind="meeting_metadata",
                        text_snippet=str(val),
                        confidence=1.0,
                    )
                )
                facts.append(
                    MeetingFact(
                        field_id=field.field_id,
                        value=val,
                        status=status,
                        evidence_refs=evidence,
                        confidence=1.0,
                        reason="Cung cấp trực tiếp từ thông tin cuộc họp (metadata)",
                    )
                )
                continue

            # 1. Organization & Document Number
            if st in (SemanticFieldType.ORGANIZATION, SemanticFieldType.DOCUMENT_NUMBER):
                val = None
                status = FactStatus.UNKNOWN
                reason = (
                    "Không tìm thấy trong nội dung âm thanh; cần nhập qua biểu mẫu hoặc metadata"
                )

            # 2. Start Time & End Time
            elif st == SemanticFieldType.MEETING_START_TIME:
                # Search opening turns or time turns
                for t in turns[:5] + turns:
                    parsed_time = _extract_time_expression(t.text, prefer="start")
                    if parsed_time and (
                        "về" not in t.text or "học" in t.text or "bắt đầu" in t.text
                    ):
                        val = f"{parsed_time}"
                        status = FactStatus.SUPPORTED
                        evidence.append(
                            EvidenceRef(
                                run_id=run_id,
                                turn_id=t.turn_id,
                                source_id=t.source_id,
                                start_sec=t.start_sec,
                                end_sec=t.end_sec,
                                clip_path=t.clip_path,
                                source_kind="transcript",
                                text_snippet=t.text,
                                confidence=0.85,
                            )
                        )
                        break
                if not val:
                    status = FactStatus.UNKNOWN
                    reason = "Không có thông tin thời gian bắt đầu trong âm thanh"

            elif st == SemanticFieldType.MEETING_END_TIME:
                # Search closing turns (last 5 turns)
                for t in reversed(turns):
                    if "kết thúc" in t.text or "về" in t.text:
                        parsed_time = _extract_time_expression(t.text, prefer="end")
                        if parsed_time:
                            val = f"{parsed_time}"
                            status = FactStatus.SUPPORTED
                            evidence.append(
                                EvidenceRef(
                                    run_id=run_id,
                                    turn_id=t.turn_id,
                                    source_id=t.source_id,
                                    start_sec=t.start_sec,
                                    end_sec=t.end_sec,
                                    clip_path=t.clip_path,
                                    source_kind="transcript",
                                    text_snippet=t.text,
                                    confidence=0.85,
                                )
                            )
                            break
                if not val:
                    status = FactStatus.UNKNOWN
                    reason = "Không có thông tin thời gian kết thúc trong âm thanh"

            # 3. Location
            elif st == SemanticFieldType.MEETING_LOCATION:
                loc_evidence = retrieve_evidence_for_field(
                    field, index, run_id, ["tại", "phòng", "địa điểm"]
                )
                if loc_evidence:
                    val = loc_evidence[0].text_snippet
                    status = FactStatus.NEEDS_REVIEW
                    evidence = loc_evidence
                    reason = "Địa điểm được trích xuất từ câu thoại, cần rà soát"
                else:
                    status = FactStatus.UNKNOWN
                    reason = "Không tìm thấy thông tin địa điểm trong cuộc họp"

            # 4. Meeting Topic
            elif st in (SemanticFieldType.MEETING_TOPIC, SemanticFieldType.MEETING_AGENDA_SUMMARY):
                if meta.get("topic"):
                    val = meta["topic"]
                    status = FactStatus.SUPPORTED
                else:
                    # Look at opening turns
                    opening_turns = [t for t in turns[:3] if len(t.text) > 15]
                    if opening_turns:
                        first_t = opening_turns[0]
                        val = first_t.text
                        status = FactStatus.SUPPORTED
                        evidence.append(
                            EvidenceRef(
                                run_id=run_id,
                                turn_id=first_t.turn_id,
                                source_id=first_t.source_id,
                                start_sec=first_t.start_sec,
                                end_sec=first_t.end_sec,
                                clip_path=first_t.clip_path,
                                source_kind="transcript",
                                text_snippet=first_t.text,
                                confidence=0.75,
                            )
                        )
                    else:
                        status = FactStatus.UNKNOWN
                        reason = "Không tìm thấy nội dung chủ đề cuộc họp"

            # 5. Attendees & Chairperson
            elif st == SemanticFieldType.PERSON_NAME:
                if "chủ" in field.raw_label.lower() or "chủ" in field.field_id:
                    val, status, evidence, reason = _explicit_role(
                        turns,
                        person_groups,
                        "chủ trì|chủ tọa",
                        run_id,
                    )
                elif "thư ký" in field.raw_label.lower():
                    val, status, evidence, reason = _explicit_role(
                        turns,
                        person_groups,
                        "thư ký|người ghi biên bản",
                        run_id,
                    )

            elif st == SemanticFieldType.ATTENDEE_LIST:
                if person_groups:
                    val = [
                        normalize_speaker_label(group[-1].speaker_label) for group in person_groups
                    ]
                    evidence = [_person_evidence(group[-1], run_id) for group in person_groups]
                    status = FactStatus.NEEDS_REVIEW
                    reason = (
                        "Danh sách người đã phát biểu, đã gộp theo danh tính; "
                        "cần xác nhận danh tính và người tham dự không phát biểu"
                    )
                else:
                    val = None
                    status = FactStatus.UNKNOWN
                    reason = "Không xác định được danh sách người tham gia"

            # 6. Discussion Summary
            elif st == SemanticFieldType.DISCUSSION_SUMMARY:
                meaningful_turns = [
                    t for t in turns if len(t.tokens) >= 5 and "a phủ" not in t.text
                ]
                if meaningful_turns:
                    val = "\n".join(f"- {t.speaker_label}: {t.text}" for t in meaningful_turns[:5])
                    status = FactStatus.SUPPORTED
                    for t in meaningful_turns[:2]:
                        evidence.append(
                            EvidenceRef(
                                run_id=run_id,
                                turn_id=t.turn_id,
                                source_id=t.source_id,
                                start_sec=t.start_sec,
                                end_sec=t.end_sec,
                                clip_path=t.clip_path,
                                source_kind="transcript",
                                text_snippet=t.text,
                                confidence=0.8,
                            )
                        )
                else:
                    status = FactStatus.UNKNOWN
                    reason = "Không có đủ nội dung thảo luận"

            # 7. Decisions & Action Items
            elif st in (SemanticFieldType.DECISION_LIST, SemanticFieldType.ACTION_ITEM):
                decision_candidates: list[IndexedTurn] = []
                for t in turns:
                    t_low = t.text.lower()
                    if any(kw in t_low for kw in DECISION_KEYWORDS):
                        # Verify not disqualified as mere proposal
                        if not any(dq in t_low for dq in PROPOSAL_DISQUALIFIERS):
                            decision_candidates.append(t)

                if decision_candidates:
                    val = [t.text for t in decision_candidates[:3]]
                    status = FactStatus.SUPPORTED
                    for dt in decision_candidates[:2]:
                        evidence.append(
                            EvidenceRef(
                                run_id=run_id,
                                turn_id=dt.turn_id,
                                source_id=dt.source_id,
                                start_sec=dt.start_sec,
                                end_sec=dt.end_sec,
                                clip_path=dt.clip_path,
                                source_kind="transcript",
                                text_snippet=dt.text,
                                confidence=0.85,
                            )
                        )
                else:
                    val = None
                    status = FactStatus.UNKNOWN
                    reason = "Không có quyết nghị rõ ràng được chốt trong cuộc họp"

            # 8. Voting
            elif "voting" in st.value:
                val = None
                status = FactStatus.UNKNOWN
                reason = "Không diễn ra biểu quyết phiếu trong cuộc họp"

            # 9. Party Specific
            elif st in (
                SemanticFieldType.PARTY_DUES,
                SemanticFieldType.PARTY_MEMBER_STATUS,
                SemanticFieldType.MORAL_STUDY,
                SemanticFieldType.RESOLUTION_EVALUATION,
                SemanticFieldType.LEADERSHIP_FEEDBACK,
            ):
                val = None
                status = FactStatus.UNKNOWN
                reason = "Không tìm thấy nội dung liên quan trong âm thanh cuộc họp thông thường"

            # 10. Signatures
            elif st == SemanticFieldType.SIGNATURE:
                val = "(Đã ký)"
                status = FactStatus.SUPPORTED
                reason = "Vị trí ký biên bản"

            # Check if any turn in evidence has needs_review or unconfident ASR
            if evidence:
                turn_ids = {e.turn_id for e in evidence}
                flagged_turns = [
                    t
                    for t in turns
                    if t.turn_id in turn_ids and (t.needs_review or t.asr_status != "transcribed")
                ]
                if flagged_turns and status == FactStatus.SUPPORTED:
                    status = FactStatus.NEEDS_REVIEW
                    reason = "Đoạn âm thanh đối chiếu có cảnh báo ASR, cần người dùng xác nhận"

            facts.append(
                MeetingFact(
                    field_id=field.field_id,
                    value=val,
                    status=status,
                    evidence_refs=evidence,
                    confidence=conf,
                    reason=reason,
                )
            )

        return facts


class M3Qwen3FactExtractor:
    """Local LLM extractor (M3) for free-form meeting fields (discussion, decisions, actions).

    Specification: Section 5 (F3) of docs/PLAN_BIEU_MAU_BIEN_BAN_V1.md.
    Strict Grounding Invariant: Summarizes ONLY from retrieved evidence turns.
    Never hallucinates claims outside the provided turn snippets.
    """

    def __init__(
        self,
        model_name: str = "qwen2.5:3b",
        base_url: str = "http://localhost:11434",
        timeout: float = 30.0,
    ) -> None:
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get_resolved_model(self) -> str | None:
        """Find an active Qwen model name from Ollama if available."""
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name", "") for m in data.get("models", [])]
                # Direct match
                if self.model_name in models:
                    return self.model_name
                # Partial match for any qwen2.5 or qwen model
                for m in models:
                    if isinstance(m, str) and "qwen" in m.lower():
                        return m
        except Exception:
            return None
        return None

    def is_available(self) -> bool:
        """Check whether Ollama runtime is reachable and has a Qwen model loaded."""
        return self.get_resolved_model() is not None

    def extract_free_form_facts(
        self,
        schema: TemplateSchema,
        turns: list[IndexedTurn],
        run_id: str,
        meeting_metadata: dict[str, Any] | None = None,
    ) -> tuple[list[MeetingFact] | None, str, float]:
        """Extract free-form facts using local LLM; returns (facts, status, duration)."""
        t0 = time.perf_counter()
        active_model = self.get_resolved_model()
        if not active_model:
            dur = time.perf_counter() - t0
            logger.info(
                "M3 model weights not available in Ollama (%s). Status: not_run",
                self.model_name,
            )
            return None, "not_run", dur

        # Filter schema for free-form fields
        target_fields = [
            f
            for f in schema.fields
            if f.semantic_type
            in (
                SemanticFieldType.DISCUSSION_SUMMARY,
                SemanticFieldType.MEETING_AGENDA_SUMMARY,
                SemanticFieldType.DECISION_LIST,
                SemanticFieldType.ACTION_ITEM,
            )
        ]
        if not target_fields:
            return [], "no_target_fields", time.perf_counter() - t0

        # Build grounded turn context
        turn_snippets = [
            f"[{t.turn_id}] {t.speaker_label} ({t.start_sec:.1f}s - {t.end_sec:.1f}s): {t.text}"
            for t in turns
            if len(t.tokens) >= 3
        ]
        context_str = "\n".join(turn_snippets[:20])

        fields_desc = [
            {"field_id": f.field_id, "label": f.raw_label, "type": f.semantic_type.value}
            for f in target_fields
        ]

        system_prompt = (
            "Bạn là trợ lý thư ký biên bản cuộc họp tiếng Việt chuyên nghiệp.\n"
            "QUY TẮC BẮT BUỘC:\n"
            "1. CHỈ sử dụng thông tin trong các lượt thoại bên dưới (grounded evidence).\n"
            "2. TUYỆT ĐỐI KHÔNG bịa đặt thông tin không có trong lượt thoại.\n"
            "3. Với 'decision_list': CHỈ ghi nhận khi cuộc họp có sự chốt hạ rõ ràng "
            "('thống nhất', 'quyết định', 'kết luận'). "
            "Không biến ý kiến đề xuất thành quyết định.\n"
            "4. Trả về đúng định dạng JSON dạng:\n"
            '{"results": [{"field_id": "...", "value": "...", "status": "supported", '
            '"reason": "...", "turn_ids": ["seg_0001"]}]}'
        )

        user_content = (
            f"Thông tin cuộc họp: {meeting_metadata or {}}\n\n"
            f"Các trường cần tóm tắt:\n{json.dumps(fields_desc, ensure_ascii=False, indent=2)}\n\n"
            f"Danh sách lượt thoại:\n{context_str}\n\n"
            "Hãy phân tích và trả về JSON kết quả."
        )

        payload = {
            "model": active_model,
            "format": "json",
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        }

        try:
            req_data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{self.base_url}/api/chat",
                data=req_data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp_obj = json.loads(resp.read().decode("utf-8"))
                msg_content = resp_obj.get("message", {}).get("content", "{}")
                parsed_json = json.loads(msg_content)

            turns_by_id = {t.turn_id: t for t in turns}
            facts: list[MeetingFact] = []

            for item in parsed_json.get("results", []):
                fid = item.get("field_id", "")
                val = item.get("value")
                stat_str = item.get("status", "supported")
                stat = FactStatus.SUPPORTED if stat_str == "supported" else FactStatus.UNKNOWN
                rsn = item.get("reason", "Trích xuất bởi M3 Qwen3")

                # Ground evidence
                used_turn_ids = item.get("turn_ids", [])
                ev_refs: list[EvidenceRef] = []
                for tid in used_turn_ids:
                    if tid in turns_by_id:
                        matched_turn = turns_by_id[tid]
                        ev_refs.append(
                            EvidenceRef(
                                run_id=run_id,
                                turn_id=matched_turn.turn_id,
                                source_id=matched_turn.source_id,
                                start_sec=matched_turn.start_sec,
                                end_sec=matched_turn.end_sec,
                                clip_path=matched_turn.clip_path,
                                source_kind="transcript",
                                text_snippet=matched_turn.text,
                                confidence=0.88,
                            )
                        )

                facts.append(
                    MeetingFact(
                        field_id=fid,
                        value=val,
                        status=stat,
                        evidence_refs=ev_refs,
                        confidence=0.85,
                        reason=rsn,
                    )
                )

            dur = time.perf_counter() - t0
            return facts, "success", dur

        except Exception as exc:
            dur = time.perf_counter() - t0
            logger.warning("M3 LLM inference failed: %s", exc)
            return None, f"error: {exc}", dur
