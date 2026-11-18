"""Graph narratives must not occupy clocks or repeat across template holes."""

import json

from test_minutes_graph import turn

from meeting_pipeline.minutes.graph_export import guard_graph_export
from meeting_pipeline.minutes.schemas import (
    CandidateAnchor,
    DocBlock,
    DocGraph,
    MeetingFact,
    TemplateField,
    TemplateSchema,
)


def fixture(tmp_path):
    blocks = []
    fields = []
    for i, (field_id, label, text) in enumerate(
        [
            ("decision", "Kết luận", "Kết luận: ........"),
            ("continuation", "Kết luận", "........"),
            ("minute", "giờ", "Cuộc họp kết thúc vào lúc ..... giờ ..... phút."),
        ]
    ):
        anchor = CandidateAnchor(
            anchor_id=field_id,
            block_id=field_id,
            element_path=f"p[{i}]",
            placeholder_text=".....",
        )
        blocks.append(
            DocBlock(
                block_id=field_id,
                order=i,
                block_type="paragraph",
                raw_text=text,
                element_path=f"p[{i}]",
                candidate_anchors=[anchor],
            )
        )
        # Deliberately reproduce an erroneous model classification of the minute.
        fields.append(
            TemplateField(
                field_id=field_id,
                anchor_id=field_id,
                raw_label=label,
                section="Kết luận",
                semantic_type="decision_list",
            )
        )
    graph = DocGraph(
        template_id="t",
        template_name="t",
        original_sha256="a",
        normalized_docx_sha256="b",
        blocks=blocks,
    )
    schema = TemplateSchema(template_id="t", template_name="t", template_hash="a", fields=fields)
    path = tmp_path / "minutes"
    path.mkdir()
    events = [
        {
            "event_id": "d",
            "kind": "decision",
            "lifecycle": "stated",
            "text": "Nhóm thống nhất sử dụng kho chung.",
        },
        {
            "event_id": "invite",
            "kind": "decision",
            "lifecycle": "stated",
            "text": "Tôi xin biểu quyết thông qua phương án.",
        },
    ]
    (path / "meeting_graph.json").write_text(json.dumps({"events": events}))
    plan = {
        "sections": [
            {
                "paragraphs": [
                    {
                        "claim_ids": ["d"],
                        "verification": "checked",
                        "text": "Nhóm thống nhất sử dụng kho chung. Các ý kiến được ghi nhận.",
                    },
                ]
            }
        ]
    }
    (path / "content_plan.json").write_text(json.dumps(plan))
    facts = [MeetingFact(field_id=f.field_id, value="Kết luận bị sao chép.") for f in fields]
    turns = [turn("Cuộc họp kết thúc vào lúc chín giờ hai phút.")]
    return schema, graph, facts, turns


def test_scoped_clock_wins_over_wrong_semantic_label_and_repeated_conclusion(tmp_path):
    args = fixture(tmp_path)
    result = {f.field_id: f for f in guard_graph_export(tmp_path, *args)}
    assert result["minute"].value == "02"
    assert result["decision"].value == "Nhóm thống nhất sử dụng kho chung."
    assert result["continuation"].value == ""
    assert result["decision"].status == "needs_review"
    report = json.loads((tmp_path / "minutes/model_report.json").read_text())
    assert {r["reason"] for r in report["export_repairs"]} == {
        "scoped_scalar_slot",
        "narrative_continuation",
    }


def test_human_edits_are_preserved_and_do_not_duplicate_into_next_hole(tmp_path):
    schema, graph, facts, turns = fixture(tmp_path)
    facts[0] = facts[0].model_copy(
        update={"value": "Nội dung người dùng sửa.", "user_edited": True}
    )
    facts[2] = facts[2].model_copy(update={"value": "03", "user_edited": True})
    result = {f.field_id: f for f in guard_graph_export(tmp_path, schema, graph, facts, turns)}
    assert result["decision"].value == "Nội dung người dùng sửa."
    assert result["minute"].value == "03"
    assert result["continuation"].value == ""


def test_graph_disabled_export_is_unchanged(tmp_path):
    schema, graph, facts, turns = fixture(tmp_path)
    (tmp_path / "minutes/meeting_graph.json").unlink()
    assert guard_graph_export(tmp_path, schema, graph, facts, turns) is facts


def test_invitation_is_not_a_conclusion_when_no_checked_prose_exists(tmp_path):
    schema, graph, facts, turns = fixture(tmp_path)
    (tmp_path / "minutes/content_plan.json").unlink()
    result = {f.field_id: f for f in guard_graph_export(tmp_path, schema, graph, facts, turns)}
    assert "xin biểu quyết" not in result["decision"].value
    assert "kho chung" in result["decision"].value
