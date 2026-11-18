"""Behavioral regressions across segmentation, wordings and document layouts."""

import json
from dataclasses import replace

import docx
import pytest

from meeting_pipeline.minutes.doc_parser import parse_template_document
from meeting_pipeline.minutes.evidence_retrieval import IndexedTurn, load_indexed_turns
from meeting_pipeline.minutes.fact_edits import merge_fact_edits
from meeting_pipeline.minutes.factuality import rewrite_risks
from meeting_pipeline.minutes.renderer import render_completed_document
from meeting_pipeline.minutes.schema_mapper import M0RuleSchemaMapper, reconcile_schema_structure
from meeting_pipeline.minutes.schemas import FactStatus, PlaceholderType, SemanticFieldType
from meeting_pipeline.minutes.structured_fields import extract_meeting_record, structured_facts
from meeting_pipeline.minutes.text_engine import make_units


def turn(text, index=0, **kwargs):
    return IndexedTurn(
        turn_id=f"t{index}",
        text=text,
        speaker_label="Người lạ 1",
        speaker_id=None,
        start_sec=index,
        end_sec=index + 1,
        tokens=[],
        source_id="s1",
        clip_path=None,
        asr_status="transcribed",
        needs_review=False,
        confidence=None,
        **kwargs,
    )


@pytest.mark.parametrize("cut", [0, 5, 9, 12, 13, 14, 15, 16])
def test_calendar_facts_do_not_depend_on_asr_partition(cut):
    text = "bắt đầu cuộc họp lúc chín giờ ngày ba tháng mười năm hai nghìn không hai mươi sáu"
    words = text.split()
    parts = [" ".join(words[:cut]), " ".join(words[cut:])] if cut else [text]
    parts = [p for p in parts if p]
    rows = [turn(p, i) for i, p in enumerate(parts)]
    facts, _ = extract_meeting_record(rows, "r")
    assert {k: facts[k].value for k in ("year", "month", "day", "start_time")} == {
        "year": "2026",
        "month": "10",
        "day": "3",
        "start_time": "09:00",
    }
    assert {ref.turn_id for ref in facts["year"].evidence_refs} <= {t.turn_id for t in rows}


@pytest.mark.parametrize("room", ["B201", "bê hai không một", "bê hai trăm linh một"])
def test_spoken_room_number_does_not_negate_meeting_clock(room):
    text = (
        "Bắt đầu cuộc họp lúc chín giờ ngày ba tháng mười năm hai nghìn không "
        f"hai mươi sáu tại phòng {room}."
    )
    facts, _ = extract_meeting_record([turn(text)], "r")
    assert facts["start_time"].value == "09:00"
    assert facts["location"].value == "phòng B201"


@pytest.mark.parametrize("state", ["chưa", "không", "dự kiến", "sẽ"])
def test_negative_or_planned_opening_stays_unknown_despite_spoken_numbers(state):
    text = f"Cuộc họp {state} bắt đầu lúc chín giờ tại phòng bê hai không một."
    facts, _ = extract_meeting_record([turn(text)], "r")
    assert "start_time" not in facts


def test_excluded_missing_and_discontinuous_audio_are_context_barriers():
    first = turn("bắt đầu cuộc họp ngày ba tháng mười năm hai nghìn không")
    last = turn("hai mươi sáu", 2)
    barriers = [
        turn("", 1),
        replace(turn("bỏ qua", 1), asr_status="excluded"),
        replace(last, start_sec=50),
        replace(last, clock_id="another"),
        replace(last, session_id="after-break"),
    ]
    for barrier in barriers[:2]:
        record, _ = extract_meeting_record([first, barrier, last], "r")
        assert "year" not in record
    for ending in barriers[2:]:
        record, _ = extract_meeting_record([first, ending], "r")
        assert "year" not in record


@pytest.mark.parametrize(
    "closing",
    [
        "Cuộc họp kết thúc lúc 09:02 cùng ngày.",
        "Chúng ta kết thúc cuộc họp lúc chín giờ hai phút cùng ngày.",
        "Tôi tuyên bố cuộc họp kết thúc vào lúc chín giờ hai phút.",
        "Hội nghị bế mạc lúc 09h02.",
    ],
)
def test_closing_grammar_variants_have_same_clock(closing):
    record, _ = extract_meeting_record([turn(closing)], "r")
    assert record["end_time"].value == "09:02"


@pytest.mark.parametrize(
    "text",
    [
        "Phiên thảo luận kết thúc lúc 09:02.",
        "Cuộc họp dự kiến kết thúc lúc 09:02.",
        "Chúng ta chưa kết thúc cuộc họp lúc 09:02.",
    ],
)
def test_part_and_hypothetical_closures_are_not_whole_meeting_facts(text):
    record, _ = extract_meeting_record([turn(text)], "r")
    assert "end_time" not in record


@pytest.mark.parametrize("name", ["Lan", "Vân", "Nguyễn Thị Mai"])
def test_named_roles_do_not_require_recognized_voices(tmp_path, name):
    document = docx.Document()
    document.add_paragraph("Chủ trì: .....")
    document.add_paragraph("Thư ký: .....")
    document.save(tmp_path / "roles.docx")
    graph = parse_template_document(tmp_path / "roles.docx")
    schema = M0RuleSchemaMapper().propose_schema(graph)
    rows = [
        turn(f"Thành phần gồm anh Phúc chủ trì, tôi là {name} làm thư ký và anh Đức là thành viên.")
    ]
    facts = structured_facts(schema, graph, rows, "r")
    assert [f.value for f in facts] == ["Phúc", name]


@pytest.mark.parametrize("partition", [1, 2, 3])
def test_vote_round_supports_partial_values_across_continuous_turns(partition):
    text = "Kết quả tổng số 20 phiếu, 18 phiếu tán thành và 2 phiếu không tán thành."
    words = text.split()
    step = (len(words) + partition - 1) // partition
    rows = [
        turn(" ".join(words[i : i + step]), j) for j, i in enumerate(range(0, len(words), step))
    ]
    facts, rounds = extract_meeting_record(rows, "r")
    assert len(rounds) == 1
    assert [facts[k].value for k in ("vote_total", "vote_yes", "vote_no", "yes_percent")] == [
        "20",
        "18",
        "2",
        "90",
    ]


def test_partial_tally_does_not_invent_missing_opposition_or_mix_rounds():
    facts, _ = extract_meeting_record(
        [turn("Tổng số ba phiếu, ba phiếu tán thành, không cao.")], "r"
    )
    assert facts["vote_total"].value == "3" and facts["yes_percent"].value == "100"
    assert "vote_no" not in facts
    facts, rounds = extract_meeting_record(
        [
            turn("Nội dung A tổng số 3 phiếu, 3 phiếu tán thành."),
            turn("Nội dung B có 2 phiếu tán thành.", 1),
        ],
        "r",
    )
    assert len(rounds) == 2
    assert "vote_total" not in facts


def test_vote_scope_headers_can_be_separate_from_tallies():
    rows = [
        turn("Biểu quyết nội dung A."),
        turn("Tổng số 3 phiếu, 3 phiếu tán thành.", 1),
        turn("Nội dung B.", 2),
        turn("Tổng số 3 phiếu, 2 phiếu tán thành và 1 phiếu không tán thành.", 3),
    ]
    facts, rounds = extract_meeting_record(rows, "r")
    assert "vote_yes" not in facts
    assert [group["vote_scope"].value for group in rounds] == ["nội dung a", "nội dung b"]
    assert [group["vote_yes"].value for group in rounds] == ["3", "2"]
    assert {ref.turn_id for ref in rounds[1]["yes_percent"].evidence_refs} == {"t3"}


@pytest.mark.parametrize("boundary", ["clock", "session", "excluded", "empty", "time_reset"])
def test_partial_votes_do_not_accumulate_across_recording_boundaries(boundary):
    first = turn("Tổng số 3 phiếu.")
    last = turn("2 phiếu tán thành.", 2)
    rows = [first]
    if boundary in {"clock", "session"}:
        last = replace(last, **{f"{boundary}_id": "after-break"})
    elif boundary == "time_reset":
        last = replace(last, start_sec=0, end_sec=1)
    elif boundary == "excluded":
        rows.append(replace(turn("phần đã bỏ", 1), asr_status="excluded"))
    else:
        rows.append(turn("", 1))
    rows.append(last)
    facts, rounds = extract_meeting_record(rows, "r")
    assert "yes_percent" not in facts
    assert len(rounds) == 2
    assert "yes_percent" not in rounds[1] and "vote_total" not in rounds[1]


@pytest.mark.parametrize("layout", ["paragraph", "table", "nested_table"])
def test_template_layout_does_not_change_field_meaning_or_rendering(tmp_path, layout):
    document = docx.Document()
    container = document
    if layout in {"table", "nested_table"}:
        container = document.add_table(rows=1, cols=1).cell(0, 0)
    if layout == "nested_table":
        container = container.add_table(rows=1, cols=1).cell(0, 0)
    container.add_paragraph("Cuộc họp kết thúc lúc ..... giờ .....")
    container.add_paragraph("Chủ trì: .....")
    path = tmp_path / f"{layout}.docx"
    document.save(path)
    graph = parse_template_document(path)
    schema = M0RuleSchemaMapper().propose_schema(graph)
    rows = [turn("Minh là chủ trì. Chúng ta kết thúc cuộc họp lúc chín giờ hai phút.")]
    facts = structured_facts(schema, graph, rows, "r")
    assert {f.value for f in facts if f.value} == {"9", "02", "Minh"}
    out = tmp_path / "completed.docx"
    render_completed_document(path, out, graph, schema, facts)
    import zipfile

    from lxml import etree

    with zipfile.ZipFile(out) as archive:
        text = " ".join(etree.fromstring(archive.read("word/document.xml")).itertext())
    assert "9" in text and "02" in text and "Minh" in text


def test_legacy_header_mapping_and_merged_cell_aliases_are_revalidated(tmp_path):
    document = docx.Document()
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "CƠ QUAN ..."
    table.cell(0, 1).text = "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\n..., ngày ... tháng ... năm ..."
    document.add_paragraph("IV. Kết luận cuộc họp:")
    document.add_paragraph("........................................")
    merged = document.add_table(rows=1, cols=2)
    merged.cell(0, 0).merge(merged.cell(0, 1)).text = "CHỦ TỌA"
    path = tmp_path / "legacy.docx"
    document.save(path)
    graph = parse_template_document(path)
    schema = M0RuleSchemaMapper().propose_schema(graph)
    header = next(f for f in schema.fields if f.anchor_id.startswith("anc_table_0_row_0_cell_1"))
    header.semantic_type = SemanticFieldType.DECISION_LIST
    alias, canonical = next(iter(graph.anchor_aliases.items()))
    duplicate = next(f for f in schema.fields if f.anchor_id == canonical).model_copy(
        update={"field_id": "legacy_duplicate", "anchor_id": alias}
    )
    schema.fields.append(duplicate)
    fixed = reconcile_schema_structure(schema, graph)
    assert (
        next(f for f in fixed.fields if f.field_id == header.field_id).semantic_type
        == SemanticFieldType.DOCUMENT_DATE_PLACE
    )
    assert len({f.anchor_id for f in fixed.fields}) == len(fixed.fields)


@pytest.mark.parametrize("second_name", ["Minh", "Lan"])
def test_editing_legacy_merged_cells_preserves_values_or_requires_review(tmp_path, second_name):
    document = docx.Document()
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).merge(table.cell(0, 1)).text = "Chủ trì: ....."
    path = tmp_path / "merged.docx"
    document.save(path)
    graph = parse_template_document(path)
    schema = M0RuleSchemaMapper().propose_schema(graph)
    facts = structured_facts(schema, graph, [turn("Minh là chủ trì.")], "r")
    # Archived graphs contain both paths for the same physical merged cell.
    block = graph.blocks[0]
    anchor = block.candidate_anchors[0]
    duplicate = anchor.model_copy(
        update={
            "anchor_id": "legacy_duplicate",
            "element_path": anchor.element_path.replace("cell[0]", "cell[1]"),
        }
    )
    graph.blocks.append(block.model_copy(update={"candidate_anchors": [duplicate]}))
    schema.fields.append(
        schema.fields[0].model_copy(
            update={"field_id": "legacy_duplicate", "anchor_id": duplicate.anchor_id}
        )
    )
    facts.append(
        facts[0].model_copy(update={"field_id": "legacy_duplicate", "value": second_name})
    )
    out = tmp_path / "completed.docx"
    if second_name == "Minh":
        render_completed_document(path, out, graph, schema, facts)
        assert docx.Document(out).tables[0].cell(0, 0).text == "Chủ trì: Minh"
    else:
        with pytest.raises(ValueError, match="giá trị mâu thuẫn"):
            render_completed_document(path, out, graph, schema, facts)


@pytest.mark.parametrize(
    "candidate",
    [
        "Lan gửi danh sách trước ngày 10 tháng 10. Hoàn tất 20 tài liệu trước ngày 12 tháng 10.",
        "Lan gửi danh sách trước ngày 12 tháng 10. Hoàn tất 20 tài liệu trước ngày 5 tháng 10.",
        "Huy gửi danh sách trước ngày 5 tháng 10. Hoàn tất 20 tài liệu trước ngày 12 tháng 10.",
    ],
)
def test_writer_rejects_changed_relationships_even_when_numbers_overlap(candidate):
    source = (
        "Theo năm, Lan gửi danh sách trước ngày năm tháng mười. "
        "Hoàn tất hai mươi tài liệu trước ngày mười hai tháng mười."
    )
    assert rewrite_risks(source, candidate, {"Lan", "Huy"})


def test_writer_accepts_equivalent_spoken_and_digital_dates_and_quantities():
    source = "Lan gửi hai mươi tài liệu trước ngày năm tháng mười."
    candidate = "Lan gửi 20 tài liệu trước ngày 05/10."
    assert rewrite_risks(source, candidate, {"Lan"}) == []


def test_fixed_signature_conflict_is_editable_and_can_be_resolved(tmp_path):
    path = tmp_path / "signature.docx"
    document = docx.Document()
    document.add_paragraph("Các thành viên cùng ký vào biên bản.")
    document.save(path)
    graph = parse_template_document(path)
    schema = M0RuleSchemaMapper().propose_schema(graph)
    facts = structured_facts(
        schema, graph, [turn("Phần chữ ký hiện chưa có và sẽ ký sau cuộc họp.")], "r"
    )
    fact = next(f for f in facts if f.status == FactStatus.CONFLICTING)
    assert graph.all_anchors[0].placeholder_type == PlaceholderType.FIXED_TEXT
    draft = tmp_path / "draft.docx"
    render_completed_document(path, draft, graph, schema, facts)
    draft_text = docx.Document(draft).paragraphs[0].text
    assert "cùng ký" not in draft_text and "Cần rà soát" in draft_text
    updated = merge_fact_edits(
        facts,
        [{"field_id": fact.field_id, "value": "sẽ kiểm tra và ký sau", "status": "supported"}],
    )
    out = tmp_path / "resolved.docx"
    render_completed_document(path, out, graph, schema, updated)
    assert docx.Document(out).paragraphs[0].text == "Các thành viên sẽ kiểm tra và ký sau."


def test_evidence_survives_legacy_paths_and_multiturn_units(tmp_path):
    clip = tmp_path / "original.wav"
    clip.write_bytes(b"evidence")
    rows = [
        {
            "turn_id": "a",
            "text": "Ngày ba tháng mười năm hai nghìn không",
            "start_sec": 0,
            "end_sec": 1,
            "evidence_clip_artifact_id": str(clip),
            "clip_artifact_id": "audio-a",
        },
        {
            "turn_id": "b",
            "text": "hai mươi sáu.",
            "start_sec": 1,
            "end_sec": 2,
            "clip_path": str(clip),
        },
    ]
    (tmp_path / "timeline.json").write_text(json.dumps({"segments": rows}))
    turns = load_indexed_turns(tmp_path)
    assert all(t.clip_path == str(clip) for t in turns)
    record, _ = extract_meeting_record(turns, "r")
    assert {r.turn_id for r in record["year"].evidence_refs} == {"a", "b"}
    assert record["year"].evidence_refs[0].clip_artifact_id == "audio-a"
    units, _ = make_units(turns)
    assert units[0].turn_ids == ["a", "b"]


@pytest.mark.parametrize(
    "source",
    [
        "Cuộc họp bắt đầu lúc 09:00 ngày 03/10/2026.",
        "Bắt đầu cuộc họp lúc chín giờ ngày ba tháng mười năm hai nghìn không hai mươi sáu.",
    ],
)
def test_equivalent_digital_and_spoken_openings(source):
    record, _ = extract_meeting_record([turn(source)], "r")
    assert record["start_time"].value == "09:00"
    assert record["year"].value == "2026"


def test_zero_in_year_does_not_negate_closure_and_end_date_uses_own_evidence():
    rows = [
        turn("Cuộc họp bắt đầu lúc 09:00 ngày 03/10/2026."),
        turn(
            "Cuộc họp kết thúc lúc chín giờ không phút "
            "ngày bốn tháng mười năm hai nghìn không hai mươi sáu.",
            1,
        ),
    ]
    record, _ = extract_meeting_record(rows, "r")
    assert record["end_time"].value == "09:00"
    assert record["end_day"].value == "4"
    assert {ref.turn_id for ref in record["end_day"].evidence_refs} == {"t1"}


def test_writer_retains_coordinated_actors_and_does_not_add_agreement():
    assert rewrite_risks(
        "Quy và Lan thực hiện đúng phần việc đã nhận.",
        "Lan thực hiện đúng phần việc đã nhận.",
        {"Lan"},
    )
    assert rewrite_risks(
        "Chúng ta kết thúc cuộc họp lúc 09:02.",
        "Các thành viên thống nhất kết thúc cuộc họp lúc 09:02.",
        set(),
    )
