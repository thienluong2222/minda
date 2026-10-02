"""Unit tests for Phase F3: Evidence retrieval, fact extraction, decision gating, and transcript editing."""

from __future__ import annotations

from pathlib import Path

from meeting_pipeline.minutes.converter import normalize_template
from meeting_pipeline.minutes.doc_parser import parse_template_document
from meeting_pipeline.minutes.evidence_retrieval import (
    IndexedTurn,
    TurnSearchIndex,
    load_indexed_turns,
)
from meeting_pipeline.minutes.fact_extractor import M2RuleFactExtractor
from meeting_pipeline.minutes.schema_mapper import M0RuleSchemaMapper
from meeting_pipeline.minutes.schemas import FactStatus

RUN_DIR = Path("data/meetings/1/runs/a6e814e4-ea36-4cc9-8992-ba60b9341ea5")
FIXTURES_DIR = Path("tests/fixtures/templates")


def test_load_indexed_turns_real_run() -> None:
    """Load indexed turns from real meeting run with schema 2.0 timeline."""
    turns = load_indexed_turns(RUN_DIR)
    assert len(turns) == 7
    assert turns[0].turn_id == "seg_0000"
    assert turns[0].speaker_label == "thiện"
    assert len(turns[0].tokens) > 5

    index = TurnSearchIndex(turns)
    results = index.search("chương trình cuốn", top_k=2)
    assert len(results) > 0
    best_turn, score = results[0]
    assert best_turn.turn_id == "seg_0000"
    assert score > 0.5


def test_fact_extraction_mau_bien_ban_hop_chung(tmp_path: Path) -> None:
    """Extract facts for mau_bien_ban_hop_chung against real meeting audio run."""
    doc_path = FIXTURES_DIR / "mau_bien_ban_hop_chung.doc"
    converted = normalize_template(doc_path, tmp_path / "norm")
    graph = parse_template_document(converted.normalized_docx_path)
    schema = M0RuleSchemaMapper().propose_schema(graph)

    turns = load_indexed_turns(RUN_DIR)
    extractor = M2RuleFactExtractor()
    facts = extractor.extract_facts(
        schema, turns, meeting_metadata={"topic": "Ôn tập thi chuyên ngành"}, run_id="run-1"
    )

    facts_by_id = {f.field_id: f for f in facts}

    # Topic from metadata
    assert facts_by_id["topic"].status == FactStatus.SUPPORTED
    assert facts_by_id["topic"].value == "Ôn tập thi chuyên ngành"

    # Start and End time parsed from speech ('hai giờ rưỡi du học ba giờ về')
    start_time_fact = [f for f in facts if f.field_id.startswith("start_time")][0]
    assert start_time_fact.status == FactStatus.SUPPORTED
    assert "14:30" in str(start_time_fact.value)

    end_time_fact = [f for f in facts if f.field_id.startswith("end_time")][0]
    assert end_time_fact.status == FactStatus.SUPPORTED
    assert "15:00" in str(end_time_fact.value)

    # Voting counts have NO evidence in this meeting -> MUST be UNKNOWN
    voting_facts = [f for f in facts if "voting" in f.field_id]
    for vf in voting_facts:
        assert vf.status == FactStatus.UNKNOWN
        assert vf.value is None


def test_fact_extraction_chi_bo_party_fields_remain_unknown(tmp_path: Path) -> None:
    """Party-specific fields with no evidence in audio MUST remain unknown and unhallucinated."""
    docx_path = FIXTURES_DIR / "bien_ban_hop_chi_bo.docx"
    converted = normalize_template(docx_path, tmp_path / "norm")
    graph = parse_template_document(converted.normalized_docx_path)
    schema = M0RuleSchemaMapper().propose_schema(graph)

    turns = load_indexed_turns(RUN_DIR)
    extractor = M2RuleFactExtractor()
    facts = extractor.extract_facts(schema, turns, run_id="run-1")

    facts_by_id = {f.field_id: f for f in facts}

    # Party dues and member status are NOT in the audio -> must be UNKNOWN
    assert facts_by_id["party_dues"].status == FactStatus.UNKNOWN
    assert facts_by_id["party_dues"].value is None
    assert "Không tìm thấy nội dung" in str(facts_by_id["party_dues"].reason)

    assert facts_by_id["party_member_status"].status == FactStatus.UNKNOWN
    assert facts_by_id["party_member_status"].value is None


def test_proposal_not_turned_into_decision() -> None:
    """Hypothetical proposals must not be falsely extracted as formal decisions."""
    # Turn 1 is a proposal; Turn 2 is an explicit consensus
    turns = [
        IndexedTurn(
            turn_id="t1",
            speaker_label="An",
            speaker_id="spk-1",
            start_sec=0.0,
            end_sec=5.0,
            text="tôi đề xuất hay là chúng ta dời lịch sang thứ hai",
            tokens=["tôi", "đề", "xuất", "hay", "là", "chúng", "ta", "dời", "lịch"],
            source_id="src-1",
            clip_path=None,
            asr_status="transcribed",
            needs_review=False,
            confidence=0.9,
        ),
        IndexedTurn(
            turn_id="t2",
            speaker_label="Bình",
            speaker_id="spk-2",
            start_sec=5.0,
            end_sec=10.0,
            text="toàn bộ cuộc họp đã thống nhất bàn giao tài liệu vào ngày mai",
            tokens=["toàn", "bộ", "cuộc", "họp", "đã", "thống", "nhất", "bàn", "giao"],
            source_id="src-1",
            clip_path=None,
            asr_status="transcribed",
            needs_review=False,
            confidence=0.9,
        ),
    ]

    schema = M0RuleSchemaMapper().propose_schema(
        parse_template_document(
            normalize_template(
                FIXTURES_DIR / "bien_ban_hop_chi_bo.docx", Path("/tmp")
            ).normalized_docx_path
        )
    )

    extractor = M2RuleFactExtractor()
    facts = extractor.extract_facts(schema, turns)
    decision_facts = [f for f in facts if "decision" in f.field_id or f.field_id == "decisions"]

    if decision_facts:
        d_val = str(decision_facts[0].value)
        assert "thống nhất bàn giao tài liệu" in d_val
        assert "hay là chúng ta dời lịch" not in d_val


def test_transcript_edit_without_asr_rerun() -> None:
    """Editing transcript updates facts immediately without invoking ASR."""
    # Initial turn with typo
    turn_with_typo = IndexedTurn(
        turn_id="t1",
        speaker_label="An",
        speaker_id="spk-1",
        start_sec=0.0,
        end_sec=5.0,
        text="kết thúc lúc mười bốn giờ ba mươi",
        tokens=["kết", "thúc", "lúc", "mười", "bốn", "giờ", "ba", "mươi"],
        source_id="src-1",
        clip_path=None,
        asr_status="transcribed",
        needs_review=False,
        confidence=0.8,
    )

    schema = M0RuleSchemaMapper().propose_schema(
        parse_template_document(
            normalize_template(
                FIXTURES_DIR / "mau_bien_ban_hop_chung.doc", Path("/tmp")
            ).normalized_docx_path
        )
    )
    extractor = M2RuleFactExtractor()
    facts_v1 = extractor.extract_facts(schema, [turn_with_typo])
    end_time_v1 = [f for f in facts_v1 if f.field_id.startswith("end_time")][0]
    assert "14:30" in str(end_time_v1.value)

    # User manually edits transcript: "kết thúc lúc mười sáu giờ đúng" (16:00)
    edited_turn = IndexedTurn(
        turn_id="t1",
        speaker_label="An",
        speaker_id="spk-1",
        start_sec=0.0,
        end_sec=5.0,
        text="kết thúc lúc mười sáu giờ",
        tokens=["kết", "thúc", "lúc", "mười", "sáu", "giờ"],
        source_id="src-1",
        clip_path=None,
        asr_status="transcribed",
        needs_review=False,
        confidence=1.0,
    )

    facts_v2 = extractor.extract_facts(schema, [edited_turn])
    end_time_v2 = [f for f in facts_v2 if f.field_id.startswith("end_time")][0]
    assert "16:00" in str(end_time_v2.value)
