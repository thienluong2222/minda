import json
from pathlib import Path

import docx
import pytest

from meeting_backend.integrations.minutes_pipeline import reconcile_regenerated_facts
from meeting_pipeline.minutes.doc_parser import parse_template_document
from meeting_pipeline.minutes.evidence_retrieval import load_indexed_turns
from meeting_pipeline.minutes.schemas import SemanticFieldType, TemplateField, TemplateSchema
from meeting_pipeline.minutes.structured_fields import structured_facts
from meeting_pipeline.minutes.text_engine import make_units


def timeline(tmp_path: Path, *rows: dict):
    (tmp_path / "timeline.json").write_text(
        json.dumps({"segments": [{"turn_id": str(i), **row} for i, row in enumerate(rows)]})
    )
    return load_indexed_turns(tmp_path)


@pytest.mark.parametrize("status", ["not_run", "failed", "empty", "transcribed"])
def test_manual_transcript_is_eligible_without_changing_raw_status(tmp_path, status):
    turns = timeline(
        tmp_path,
        {"asr_status": status, "text": "Thống nhất triển khai.", "user_edited": True},
        {"asr_status": status, "text": "", "user_edited": True},
        {
            "asr_status": status,
            "text": "Nội dung đã loại.",
            "user_edited": True,
            "excluded_from_minutes": True,
        },
    )
    units, _ = make_units(turns)
    assert [(u.turn_id, u.text) for u in units] == [("0", "Thống nhất triển khai.")]
    assert turns[0].asr_status == "user_edited"
    assert turns[2].text == ""
    assert (
        json.loads((tmp_path / "timeline.json").read_text())["segments"][0]["asr_status"] == status
    )


def scalar_facts(tmp_path, fields, utterances):
    path = tmp_path / "template.docx"
    document = docx.Document()
    for label, _ in fields:
        document.add_paragraph(label)
    document.save(path)
    graph = parse_template_document(path)
    schema = TemplateSchema(
        template_id=graph.template_id,
        template_name="Kiểm thử",
        template_hash="test",
        fields=[
            TemplateField(
                field_id=kind.value, anchor_id=anchor.anchor_id, raw_label=label, semantic_type=kind
            )
            for (label, kind), anchor in zip(fields, graph.all_anchors, strict=True)
        ],
    )
    return structured_facts(schema, graph, timeline(tmp_path, *utterances), "test")


@pytest.mark.parametrize(
    ("statements", "value"),
    [
        (["Phiên một kết thúc lúc mười giờ."], None),
        (
            [
                "Phiên một kết thúc lúc mười giờ.",
                "Toàn bộ cuộc họp kết thúc lúc mười một giờ.",
                "Phiên hai kết thúc lúc mười hai giờ.",
            ],
            "11:00",
        ),
        (["Cuộc họp dự kiến kết thúc lúc 14:30."], None),
        (["Cuộc họp kết thúc lúc 14:30.", "Cuộc họp kết thúc lúc 15:30."], None),
        (["Cuộc họp kết thúc lúc ba giờ rưỡi chiều."], "15:30"),
    ],
)
def test_end_time_uses_whole_meeting_and_agreement(tmp_path, statements, value):
    (fact,) = scalar_facts(
        tmp_path,
        [("Giờ bế mạc: .....", SemanticFieldType.MEETING_END_TIME)],
        [{"text": statement} for statement in statements],
    )
    assert fact.value == value
    assert fact.status == ("supported" if value else "unknown")


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        ([], ["20", "18", "2"]),
        (["Nội dung B có mười lăm phiếu tán thành."], [None, None, None]),
        (
            ["Nội dung B có tổng số 8 phiếu, 7 phiếu tán thành và 1 phiếu không tán thành."],
            [None, None, None],
        ),
    ],
)
def test_vote_counts_only_use_one_complete_tally(tmp_path, extra, expected):
    fields = [
        ("Tổng số ..... phiếu", SemanticFieldType.VOTING_TOTAL),
        ("Số phiếu tán thành .....", SemanticFieldType.VOTING_APPROVED_COUNT),
        ("Số phiếu không tán thành .....", SemanticFieldType.VOTING_REJECTED_COUNT),
    ]
    statements = [
        "Nội dung A có tổng số hai mươi phiếu, mười tám phiếu tán thành "
        "và hai phiếu không tán thành.",
        *extra,
    ]
    facts = scalar_facts(tmp_path, fields, [{"text": text} for text in statements])
    assert [fact.value for fact in facts] == expected
    assert all(fact.status == ("supported" if expected[0] else "unknown") for fact in facts)


def test_regeneration_keeps_previous_edit_separate_from_current_evidence():
    schema = {"fields": [{"field_id": "end_time", "anchor_id": "first"}]}
    edited = {"field_id": "end_time", "value": "10:00", "status": "supported", "user_edited": True}
    generated = {
        "field_id": "end_time",
        "value": "11:00",
        "status": "supported",
        "evidence_refs": [{"turn_id": "new-turn"}],
    }
    old = {"_id": "old", "schema": schema, "facts": [edited]}
    assert reconcile_regenerated_facts(old, [generated], schema, unchanged_input=True) == [edited]
    expected = {
        **generated,
        "status": "conflicting",
        "previous_edit": {"value": "10:00", "minutes_version_id": "old"},
    }
    assert reconcile_regenerated_facts(old, [generated], schema, unchanged_input=False) == [
        expected
    ]
    regenerated = {**old, "_id": "new", "facts": [expected]}
    assert reconcile_regenerated_facts(regenerated, [generated], schema, unchanged_input=True) == [
        expected
    ]
    changed = {"fields": [{"field_id": "end_time", "anchor_id": "second"}]}
    assert reconcile_regenerated_facts(old, [generated], changed, unchanged_input=True) == [
        generated
    ]
