"""Behavioral gates for content ownership, risky edits and template preservation."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import docx
import numpy as np
import pytest

from meeting_pipeline.minutes.converter import compute_file_sha256
from meeting_pipeline.minutes.doc_parser import parse_template_document
from meeting_pipeline.minutes.evidence_retrieval import IndexedTurn
from meeting_pipeline.minutes.model_runtime import ModelRuntimeError, ModelSession
from meeting_pipeline.minutes.renderer import render_completed_document
from meeting_pipeline.minutes.schema_mapper import M0RuleSchemaMapper
from meeting_pipeline.minutes.schemas import FactStatus, MeetingFact
from meeting_pipeline.minutes.structured_fields import structured_facts, vietnamese_number
from meeting_pipeline.minutes.text_engine import (
    MinutesOptions,
    TextEngine,
    correction_risks,
    make_units,
)
from meeting_pipeline.minutes.topic_clustering import cluster_topics


def test_fcm_recovers_two_distinct_topics_without_duplicate_ownership() -> None:
    rng = np.random.default_rng(5)
    x = np.vstack([rng.normal([1, 0, 0], 0.02, (8, 3)), rng.normal([0, 1, 0], 0.02, (8, 3))])
    result = cluster_topics(x.tolist())
    assert result["cluster_count"] == 2
    assert result["primary"] == [0] * 8 + [1] * 8
    assert len(result["membership"]) == 16
    assert np.allclose(np.sum(result["membership"], axis=1), 1)
    assert result["membership_is_probability"] is False


def test_fcm_keeps_identical_or_short_meeting_in_one_topic() -> None:
    assert cluster_topics([[1, 0]] * 12)["cluster_count"] == 1
    assert cluster_topics([[1, 0], [0, 1]])["primary"] == [0, 0]
    with pytest.raises(ValueError):
        cluster_topics([[float("nan"), 0]])
    with pytest.raises(ValueError):
        cluster_topics([[1, 0]], fixed_clusters=2)


@pytest.mark.parametrize(
    ("original", "candidate", "risk"),
    [
        (
            "Chưa thống nhất ngày 12/10.",
            "Đã thống nhất ngày 12/10.",
            "changed_condition_negation_or_decision",
        ),
        ("Lan nhập 20 tài liệu.", "Lan nhập 200 tài liệu.", "changed_digits"),
        ("Hạn là ngày sáu tháng mười.", "Hạn là ngày tám tháng mười.", "changed_number_words"),
    ],
)
def test_correction_rejects_changes_to_decisions_and_numbers(
    original: str,
    candidate: str,
    risk: str,
) -> None:
    assert risk in correction_risks(original, candidate)


def test_correct_transcript_is_not_forced_to_change() -> None:
    assert not correction_risks("Lan kiểm tra phân quyền.", "Lan kiểm tra phân quyền.")


@pytest.mark.parametrize(
    "failure",
    ["changed_number", "missing_number", "changed_owner", "added_completion", "missing_id"],
)
def test_writer_keeps_source_when_numbers_change_or_coverage_is_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    template = tmp_path / "body.docx"
    document = docx.Document()
    document.add_paragraph("Nội dung cuộc họp:")
    document.add_paragraph("........................................")
    document.save(template)
    graph = parse_template_document(template)
    body = M0RuleSchemaMapper().propose_schema(graph).fields[0]
    turn = IndexedTurn(
        turn_id="t1",
        speaker_label="Huy",
        speaker_id="huy",
        start_sec=0,
        end_sec=5,
        text="Huy nhập 20 tài liệu. Lan kiểm tra quyền xem.",
        tokens=[],
        source_id="s1",
        clip_path=None,
        asr_status="transcribed",
        needs_review=False,
        confidence=None,
    )
    units, _ = make_units([turn])
    session = ModelSession(tmp_path / "unused.log")
    monkeypatch.setattr(session, "token_count", lambda text: len(text.split()))
    items = [{"unit_id": u.unit_id, "text": u.text} for u in units]
    if failure == "changed_number":
        items[0]["text"] = "Huy nhập 200 tài liệu."
    elif failure == "missing_number":
        items[0]["text"] = "Huy nhập tài liệu."
    elif failure == "changed_owner":
        items[0]["text"] = "Lan nhập 20 tài liệu."
    elif failure == "added_completion":
        items[0]["text"] = "Huy đã nhập 20 tài liệu."
    else:
        items.pop()
    monkeypatch.setattr(
        session, "generate_json", lambda *args: {"title": "Công việc", "items": items}
    )
    engine = TextEngine(session, "test")
    fact, topics = engine.write_general(
        units, MinutesOptions(use_model=True, mode="general", use_fcm=False), [turn], body
    )
    assert "Huy nhập 20 tài liệu." in str(fact.value)
    assert "200" not in str(fact.value)
    assert "Lan kiểm tra quyền xem." in str(fact.value)
    assert topics["coverage_complete"] is True
    assert engine.warnings


@pytest.mark.parametrize(
    ("spoken", "number"),
    [
        ("hai nghìn không trăm hai mươi sáu", 2026),
        ("hai không một", 201),
        ("mười hai", 12),
        ("hai mươi", 20),
        ("một trăm", 100),
        ("không", 0),
    ],
)
def test_vietnamese_metadata_number_normalization(spoken: str, number: int) -> None:
    assert vietnamese_number(spoken) == number


def test_truncated_generation_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    session = ModelSession(tmp_path / "unused.log")
    monkeypatch.setattr(
        session,
        "request",
        lambda *args, **kwargs: {
            "text": '{"items":[]}',
            "finish_reason": "length",
        },
    )
    with pytest.raises(ModelRuntimeError, match="token"):
        session.generate_json("unique truncation test", {"id": str(tmp_path)})


def test_renderer_preserves_all_opaque_parts_and_fixed_labels(tmp_path: Path) -> None:
    template = tmp_path / "template.docx"
    doc = docx.Document()
    doc.add_heading("Nội dung cuộc họp", level=1)
    p = doc.add_paragraph()
    p.add_run("Đề mục cố định: ").bold = True
    p.add_run("... ")
    p.add_run("... Kết thúc").italic = True
    doc.add_paragraph("........................................")
    doc.sections[0].header.paragraphs[0].text = "Header phải giữ nguyên"
    doc.save(template)
    graph = parse_template_document(template)
    schema = M0RuleSchemaMapper().propose_schema(graph)
    inline = next(
        f for f in schema.fields if f.anchor_id == graph.blocks[1].candidate_anchors[0].anchor_id
    )
    body = next(
        f for f in schema.fields if f.anchor_id == graph.blocks[2].candidate_anchors[0].anchor_id
    )
    before = compute_file_sha256(template)
    out = tmp_path / "completed.docx"
    render_completed_document(
        template,
        out,
        graph,
        schema,
        [
            MeetingFact(field_id=inline.field_id, value="đã điền", status=FactStatus.NEEDS_REVIEW),
            MeetingFact(
                field_id=body.field_id,
                value="1. Phân quyền\nLan kiểm tra quyền xem.\n"
                "2. Nhập tài liệu\nHuy nhập tài liệu.",
                status=FactStatus.NEEDS_REVIEW,
            ),
        ],
        general_content_field_id=body.field_id,
    )
    assert compute_file_sha256(template) == before
    completed = docx.Document(out)
    assert completed.paragraphs[0].text == "Nội dung cuộc họp"
    assert completed.paragraphs[1].runs[0].bold is True
    assert completed.paragraphs[1].runs[-1].italic is True
    assert "Kết thúc" in completed.paragraphs[1].text
    assert any(p.text == "2. Nhập tài liệu" for p in completed.paragraphs)
    with zipfile.ZipFile(template) as a, zipfile.ZipFile(out) as b:
        assert a.namelist() == b.namelist()
        for part in a.namelist():
            if part != "word/document.xml":
                assert a.read(part) == b.read(part), part


def test_renderer_fills_exact_repeated_slot_with_unknown_slots_before_it(tmp_path: Path) -> None:
    template = tmp_path / "repeated.docx"
    document = docx.Document()
    document.add_paragraph("Kết thúc lúc ..... giờ ..... ngày ..... tháng ..... năm .....")
    cell = document.add_table(rows=1, cols=1).cell(0, 0)
    cell.paragraphs[0].text = "Ngày ....."
    cell.add_paragraph("Ngày .....")
    document.save(template)
    graph = parse_template_document(template)
    schema = M0RuleSchemaMapper().propose_schema(graph)
    fields = {f.anchor_id: f for f in schema.fields}
    anchors = graph.blocks[0].candidate_anchors
    facts = [
        MeetingFact(field_id=fields[a.anchor_id].field_id, value=value, status=FactStatus.SUPPORTED)
        for a, value in zip(anchors[2:], ["3", "10", "2026"], strict=True)
    ]
    last = next(a for a in graph.all_anchors if "/cell[0]/p[1]/" in a.element_path)
    facts.append(
        MeetingFact(
            field_id=fields[last.anchor_id].field_id, value="12", status=FactStatus.SUPPORTED
        )
    )
    output = tmp_path / "completed.docx"
    render_completed_document(template, output, graph, schema, facts)
    completed = docx.Document(output)
    assert completed.paragraphs[0].text == "Kết thúc lúc ..... giờ ..... ngày 3 tháng 10 năm 2026"
    assert completed.tables[0].cell(0, 0).text == "Ngày .....\nNgày 12"


def test_metadata_does_not_infer_end_date_and_bounds_unpunctuated_location(tmp_path: Path) -> None:
    template = tmp_path / "metadata.docx"
    document = docx.Document()
    document.add_paragraph("Hôm nay vào lúc ..... giờ ..... ngày ..... tháng ..... năm .....")
    document.add_paragraph("Tại ........................................")
    document.add_paragraph(
        "Cuộc họp kết thúc vào lúc ..... giờ ..... ngày ..... tháng ..... năm ....."
    )
    document.save(template)
    graph = parse_template_document(template)
    schema = M0RuleSchemaMapper().propose_schema(graph)
    turn = IndexedTurn(
        turn_id="start",
        speaker_label="Lan",
        speaker_id="lan",
        start_sec=0,
        end_sec=8,
        text="Tôi bắt đầu cuộc họp lúc chín giờ ngày ba tháng mười năm hai nghìn không trăm "
        "hai mươi sáu tại phòng bê hai không một đây là cuộc họp của nhóm dự án về việc thử nghiệm",
        tokens=[],
        source_id="s1",
        clip_path=None,
        asr_status="transcribed",
        needs_review=False,
        confidence=None,
    )
    facts = {f.field_id: f for f in structured_facts(schema, graph, [turn], "test")}
    fields = {f.anchor_id: f for f in schema.fields}
    location_anchor = graph.blocks[1].candidate_anchors[0]
    assert facts[fields[location_anchor.anchor_id].field_id].value == "phòng B201"
    for anchor in graph.blocks[2].candidate_anchors:
        assert facts[fields[anchor.anchor_id].field_id].value is None


def test_transaction_rolls_back_failed_model_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from meeting_pipeline.minutes.service import MinutesService

    run = tmp_path / "run"
    (run / "minutes").mkdir(parents=True)
    facts = run / "minutes/facts.json"
    facts.write_text(json.dumps([{"value": "Bản người dùng đã sửa"}]))
    before = facts.read_bytes()
    service = MinutesService()

    def fail(*args: object) -> dict[str, object]:
        facts.write_text("broken partial output")
        raise ModelRuntimeError("inference failed")

    monkeypatch.setattr(service, "_process_template_for_run", fail)
    with pytest.raises(ModelRuntimeError):
        service.process_template_for_run(tmp_path / "unused.docx", run)
    assert facts.read_bytes() == before
