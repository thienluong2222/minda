"""Behavioral regression gates for graph-grounded minutes and independent style memory."""

from types import SimpleNamespace

import numpy as np
import pytest

from meeting_pipeline.minutes.evidence_retrieval import IndexedTurn
from meeting_pipeline.minutes.graph_builder import (
    build_graph,
    fallback_event,
    validate_event,
    validate_graph,
)
from meeting_pipeline.minutes.graph_contracts import Event, default_style, remap_identifiers
from meeting_pipeline.minutes.graph_inputs import make_graph_units
from meeting_pipeline.minutes.graph_topics import discover_topics
from meeting_pipeline.minutes.graph_writer import packet_for, plan_sections, write_sections
from meeting_pipeline.minutes.style_memory import learn_style_rules


def turn(text, key="turn1", speaker="An", status="transcribed"):
    return IndexedTurn(
        turn_id=key,
        speaker_label=speaker,
        speaker_id=speaker,
        start_sec=0,
        end_sec=3,
        text=text,
        tokens=[],
        source_id="mic1",
        clip_path=None,
        asr_status=status,
        needs_review=False,
        confidence=None,
    )


def topics(n, membership=None):
    u = membership or [[1.0]] * n
    return {
        "membership": u,
        "primary": np.argmax(u, axis=1).tolist(),
        "cluster_count": len(u[0]),
        "titles": [f"Chủ đề {i}" for i in range(len(u[0]))],
    }


def test_graph_spans_reconstruct_source_and_ids_survive_unrelated_insertions():
    source = turn("  An đề nghị ngày 15/11. Bình phản đối; chưa thống nhất.")
    units, excluded = make_graph_units([source, turn("", "empty")])
    assert len(units) == 3 and len(excluded) == 1
    for u in units:
        span = u.sources[0]
        assert source.text[span.start_char : span.end_char] == span.text == u.original
        assert u.start_sec == 0 and u.end_sec == 3
    inserted, _ = make_graph_units([turn("Chào mọi người.", "unrelated"), source])
    assert [u.unit_id for u in inserted[1:]] == [u.unit_id for u in units]


@pytest.mark.parametrize(
    "text", ["Tôi chưa thống nhất phương án này.", "Xin biểu quyết phương án này."]
)
def test_invitation_or_negation_cannot_establish_decision(text):
    unit = make_graph_units([turn(text)])[0][0]
    event = validate_event({"kind": "decision"}, unit, {unit.unit_id: unit})
    assert event.kind == "unresolved"
    assert event.lifecycle != "accepted"


def test_unknown_owner_deadline_and_source_are_rejected():
    unit = make_graph_units([turn("An rà hồ sơ.")])[0][0]
    event = validate_event(
        {"kind": "task", "owner": "Bình", "deadline": "20/11"}, unit, {unit.unit_id: unit}
    )
    assert event.owner is None and event.deadline is None
    assert "unsupported_owner" in event.warnings
    with pytest.raises(ValueError, match="Bằng chứng"):
        validate_event({"evidence_unit_ids": ["invented"]}, unit, {unit.unit_id: unit})


def test_rejecting_filler_cannot_drop_short_material_dissent():
    unit = make_graph_units([turn("Không đồng ý.")])[0][0]
    event = validate_event({"kind": "filler"}, unit, {unit.unit_id: unit})
    graph = build_graph("m", [unit], [event], topics(1), [])
    sections, ledger = plan_sections(graph)
    assert len(sections) == 1
    assert ledger[0]["disposition"] == "included"


def test_cross_session_or_wrong_version_does_not_promote_proposal():
    turns = [turn("Đề nghị thông qua V1.", "a"), turn("Phiên này thông qua V3.", "b")]
    units, _ = make_graph_units(turns, {"turn_sessions": {"a": "group_A", "b": "plenary"}})
    events = [
        Event(
            event_id="e_" + u.unit_id,
            unit_ids=[u.unit_id],
            text=u.text,
            kind="proposal" if i == 0 else "decision",
            session_id=u.session_id,
            lifecycle="proposed" if i == 0 else "stated",
            document_version="V1" if i == 0 else "V3",
        )
        for i, u in enumerate(units)
    ]
    graph = build_graph(
        "m",
        units,
        events,
        topics(2),
        [
            {
                "source": events[1].event_id,
                "target": events[0].event_id,
                "kind": "accepts",
                "evidence_ids": [u.unit_id for u in units],
            }
        ],
    )
    assert graph.events[0].lifecycle == "proposed"
    assert not validate_graph(graph)
    assert any(e.kind == "refers_to" and not e.asserted for e in graph.edges)


def test_supported_withdrawal_retains_history_and_retrieves_old_source():
    units, _ = make_graph_units(
        [turn("Tôi đề nghị hạn 15/11.", "a"), turn("Tôi rút đề xuất hạn 15/11.", "b")]
    )
    events = [fallback_event(u) for u in units]
    events[0].kind = "proposal"
    events[0].lifecycle = "proposed"
    relation = {
        "source": events[1].event_id,
        "target": events[0].event_id,
        "kind": "withdraws",
        "evidence_ids": [u.unit_id for u in units],
    }
    graph = build_graph("m", units, events, topics(2), [relation])
    assert graph.events[0].lifecycle == "withdrawn"
    assert graph.events[0].text == units[0].text
    packet = packet_for(graph, [events[1].event_id], use_graph=True, soft=False)
    assert {u.unit_id for u in units}.issubset({r["unit_id"] for r in packet["sources"]})


@pytest.mark.parametrize(
    "text,kind,relation",
    [
        ("Tôi không rút đề xuất hạn 15/11.", "withdrawal", "withdraws"),
        ("Tôi đề nghị thông qua đề xuất hạn 15/11.", "proposal", "accepts"),
    ],
)
def test_negated_or_proposed_transition_cannot_change_prior_state(text, kind, relation):
    units, _ = make_graph_units([turn("Đề xuất hạn 15/11.", "a"), turn(text, "b")])
    events = [fallback_event(u) for u in units]
    events[0].kind = "proposal"
    events[0].lifecycle = "proposed"
    events[1].kind = kind
    graph = build_graph(
        "m",
        units,
        events,
        topics(2),
        [
            {
                "source": events[1].event_id,
                "target": events[0].event_id,
                "kind": relation,
                "evidence_ids": [u.unit_id for u in units],
            }
        ],
    )
    assert graph.events[0].lifecycle == "proposed"
    assert any(edge.kind == "refers_to" and not edge.asserted for edge in graph.edges)


def test_soft_membership_changes_retrieval_without_establishing_facts():
    units, _ = make_graph_units([turn("Nội dung " + str(i), str(i)) for i in range(5)])
    events = [fallback_event(u) for u in units]
    membership = [[0.9, 0.1], [0.1, 0.9], [0.5, 0.5], [0.1, 0.9], [0.9, 0.1]]
    graph = build_graph("m", units, events, topics(5, membership), [], soft=True)
    hard = packet_for(graph, [events[0].event_id], use_graph=True, soft=False)
    soft = packet_for(graph, [events[0].event_id], use_graph=True, soft=True)
    assert len(soft["sources"]) > len(hard["sources"])
    assert not any(e.kind == "accepts" for e in graph.edges)
    assert all(not e.asserted for e in graph.edges if e.kind == "about")


def test_short_meeting_and_unmatched_agenda_keep_all_input():
    class Session:
        settings = SimpleNamespace(max_clusters=4, fuzziness=1.3, minimum_silhouette=0.08)

        def embed(self, texts):
            return [[1, 0] if "ngân sách" in t else [0, 1] for t in texts]

    units, _ = make_graph_units([turn("Máy chủ mất kết nối.")])
    result, _ = discover_topics(Session(), units, agenda=["ngân sách"])
    assert result["residual_indices"] == [0]
    assert len(result["membership"]) == 1
    assert sum(result["membership"][0]) == pytest.approx(1)


def test_writer_rejects_invented_values_and_keeps_explicit_source_fallback():
    units, _ = make_graph_units([turn("An gửi 20 hồ sơ.")])
    events = [fallback_event(units[0])]
    graph = build_graph("m", units, events, topics(1), [])
    sections, _ = plan_sections(graph)

    class Session:
        settings = SimpleNamespace(input_token_budget=6144, output_token_budget=2048)

        def token_count(self, text):
            return len(text.split())

        def generate_json(self, system, payload):
            if "Kiểm tra từng đoạn" in system:
                return {
                    "checks": [
                        {"paragraph_index": 0, "verdict": "supported", "missing_claim_ids": []}
                    ]
                }
            return {
                "paragraphs": [
                    {
                        "text": "An gửi 200 hồ sơ.",
                        "claim_ids": [events[0].event_id],
                        "evidence_ids": [units[0].unit_id],
                    }
                ]
            }

    written, audit = write_sections(Session(), graph, sections)
    assert written[0].paragraphs[0].text == "An gửi 20 hồ sơ."
    assert written[0].paragraphs[0].verification == "source_fallback"
    assert audit[0]["checks"][0]["risks"]


@pytest.mark.parametrize(
    ("spelled", "digital"),
    [
        ("một trăm phần trăm", "100%"),
        ("sáu mươi phần trăm", "60 %"),
        ("không phần trăm", "0%"),
    ],
)
def test_percentage_spelling_preserves_value_without_accepting_another_value(spelled, digital):
    from meeting_pipeline.minutes.graph_values import canonical_values

    assert canonical_values(spelled) == canonical_values(digital)
    assert canonical_values(spelled) != canonical_values("99%")


@pytest.mark.parametrize(
    ("spelled", "digital", "opposite"),
    [
        ("không có phiếu không tán thành", "0 phiếu không tán thành", "0 phiếu tán thành"),
        ("ba phiếu tán thành", "3 phiếu tán thành", "3 phiếu không tán thành"),
    ],
)
def test_vote_spelling_preserves_count_and_polarity(spelled, digital, opposite):
    from meeting_pipeline.minutes.graph_values import canonical_values

    assert canonical_values(spelled) == canonical_values(digital)
    assert canonical_values(spelled) != canonical_values(opposite)


def test_fallback_attributes_first_person_and_final_presentation_is_idempotent():
    from meeting_pipeline.minutes.graph_writer import finalize_graph_sections, source_paragraphs

    units, _ = make_graph_units([turn("Tôi nhận việc rà hồ sơ.", speaker="An — tổ trưởng")])
    events = [fallback_event(units[0])]
    graph = build_graph("m", units, events, topics(1), [])
    sections, _ = plan_sections(graph)
    sections[0].title = "Đề mục ngắn có căn cứ"
    sections[0].paragraphs = source_paragraphs(graph, sections[0].claim_ids)
    sections = finalize_graph_sections(graph, sections)
    assert sections[0].paragraphs[0].text == "An nhận việc rà hồ sơ."
    assert sections[0].title == graph.topics["titles"][0]
    once = [s.model_dump() for s in sections]
    assert [s.model_dump() for s in finalize_graph_sections(graph, sections)] == once


@pytest.mark.parametrize(
    "text", ["Tôi nhận việc theo bản v12, hạn 15/11.", "Lan nhận việc theo bản v12, hạn 15/11."]
)
def test_extracted_slots_do_not_match_inside_another_name_date_or_version(text):
    units, _ = make_graph_units([turn(text, speaker="Lan — thư ký")])
    unit = units[0]
    available = {unit.unit_id: unit}
    wrong = validate_event(
        {"kind": "task", "owner": "An", "deadline": "5/11", "document_version": "v1"},
        unit,
        available,
    )
    assert wrong.owner is wrong.deadline is wrong.document_version is None
    correct = validate_event(
        {"kind": "task", "owner": "Lan", "deadline": "15/11", "document_version": "v12"},
        unit,
        available,
    )
    assert correct.owner == "Lan" and correct.deadline == "15/11"
    assert correct.document_version == "v12"


@pytest.mark.parametrize(
    ("raw", "allowed"),
    [
        ('{"value":"giữ nguyên nội dung"}"', True),
        ('{"value":"giữ nguyên nội dung"} {"value":"nội dung khác"}', False),
        ('{"value":"giữ nguyên nội dung"} "ghi chú thêm"', False),
    ],
)
def test_json_reader_repairs_a_lone_quote_without_discarding_other_content(tmp_path, raw, allowed):
    from meeting_pipeline.minutes.model_runtime import (
        ModelRuntimeError,
        ModelSession,
        ModelSettings,
    )

    class Session(ModelSession):
        def request(self, op, **payload):
            assert op == "chat" and payload["max_tokens"] > 0
            metrics = {"finish_reason": "stop", "generation_tokens": 12}
            self.calls.append(metrics)
            return {**metrics, "text": raw}

    settings = ModelSettings(
        model_id="test",
        model_revision="test",
        embedding_id="test",
        embedding_revision="test",
        cache_dir=str(tmp_path / "cache"),
    )
    session = Session(tmp_path / "log.txt", settings)
    if allowed:
        assert session.generate_json("system", {}) == {"value": "giữ nguyên nội dung"}
        assert session.calls[-1]["format_repair"] == "redundant_closing_quote"
    else:
        with pytest.raises(ModelRuntimeError):
            session.generate_json("system", {})


@pytest.mark.parametrize(
    ("source", "allowed"),
    [
        ("Cuộc họp thống nhất thực hiện phương án này.", True),
        ("Cuộc họp chưa thống nhất thực hiện phương án này.", False),
        ("Tôi đề nghị cuộc họp thống nhất thực hiện phương án này.", False),
        ("Nếu cuộc họp thống nhất thực hiện phương án này thì triển khai.", False),
        ("Cuộc họp sẽ thống nhất thực hiện phương án này.", False),
    ],
)
def test_past_aspect_is_allowed_only_for_an_established_decision(source, allowed):
    from meeting_pipeline.minutes.graph_writer import deterministic_risks

    risks = deterministic_risks("Cuộc họp đã thống nhất thực hiện phương án này.", source)
    assert ("introduced_state:đã thống nhất" not in risks) is allowed


def test_style_learning_is_confirmed_deduplicated_and_separate_from_facts():
    base = default_style()
    edit = {
        "edit_id": "e1",
        "before": "An phát biểu. An cho biết tiến độ.",
        "after": "Về tiến độ, An nêu ý kiến.",
        "approved": True,
        "facts_unchanged": True,
        "names": ["An"],
    }
    one, _ = learn_style_rules(base, [edit, edit])
    assert all(not r.active for r in one.rules if r.rule_id.startswith("learned_"))
    two, _ = learn_style_rules(one, [{**edit, "edit_id": "e2"}])
    assert any(r.active for r in two.rules if r.rule_id.startswith("learned_"))
    again, _ = learn_style_rules(two, [edit])
    assert again == two
    rejected, audit = learn_style_rules(
        two, [{**edit, "edit_id": "e3", "after": "An gửi 200 hồ sơ."}]
    )
    assert rejected == two
    assert audit["rejected"]


def test_field_provenance_keeps_original_and_current_deadline_separate():
    units, _ = make_graph_units(
        [
            turn("Giao Lan gửi dự thảo trước 15/6 nếu pháp chế duyệt.", "a"),
            turn("Chốt đổi hạn gửi dự thảo từ 15/6 sang 17/6.", "b"),
        ]
    )
    available = {unit.unit_id: unit for unit in units}
    first = validate_event(
        {"kind": "task", "owner": "Lan", "deadline": "15/6", "condition": "nếu pháp chế duyệt"},
        units[0],
        available,
    )
    second = validate_event({"kind": "amendment", "deadline": "17/6"}, units[1], available)
    graph = build_graph(
        "m",
        units,
        [first, second],
        topics(2),
        [
            {
                "source": second.event_id,
                "target": first.event_id,
                "kind": "amends",
                "field": "deadline",
                "evidence_ids": list(available),
            }
        ],
    )
    assert validate_graph(graph) == []
    event = graph.events[0]
    assert event.deadline == "15/6"
    assert event.field_evidence["deadline"].unit_id == units[0].unit_id
    assert event.current_value("deadline") == "17/6"
    assert event.current_evidence("deadline").unit_id == units[1].unit_id
    assert event.current_value("condition") == "nếu pháp chế duyệt"
    assert graph.issues[0].event_ids == [first.event_id, second.event_id]
    assert graph.issues[0].effective_event_ids == [first.event_id]
    packet = packet_for(graph, [first.event_id], use_graph=True, soft=False)
    assert packet["claims"][0]["update_evidence_ids"] == [units[1].unit_id]
    assert packet["claims"][0]["deadline"] == "17/6"


def test_field_provenance_rejects_other_tasks_and_dates_mentioned_as_previous():
    units, _ = make_graph_units(
        [
            turn("Chủ trì giao Lan rà hồ sơ A trước 15/6.", "a"),
            turn("Giao Minh gửi hồ sơ B trước 17/6.", "b"),
            turn("Sửa hạn của Lan từ 15/6 chuyển sang 19/6.", "c"),
        ]
    )
    available = {unit.unit_id: unit for unit in units}
    event = validate_event(
        {
            "kind": "task",
            "deadline": "17/6",
            "owner": "Chủ trì",
            "evidence_unit_ids": [units[1].unit_id],
        },
        units[0],
        available,
    )
    assert event.deadline is None and event.owner is None
    assert event.field_evidence == {}
    amendment = validate_event({"kind": "amendment", "deadline": "15/6"}, units[2], available)
    assert amendment.deadline is None


def test_presence_in_source_does_not_turn_a_statement_into_a_condition():
    unit = make_graph_units(
        [turn("Tôi sẽ giữ mốc dự kiến như vậy và chưa điền ngày trong thông báo nháp.")]
    )[0][0]
    event = validate_event(
        {"kind": "agreement", "condition": "giữ mốc dự kiến"}, unit, {unit.unit_id: unit}
    )
    assert event.condition is None
    assert "condition" not in event.field_evidence


def test_deadline_guard_detects_swapped_values_from_the_same_source():
    from meeting_pipeline.minutes.graph_contracts import Paragraph
    from meeting_pipeline.minutes.graph_writer import deterministic_risks, verify_paragraphs

    data = [
        (turn("Lan phụ trách hồ sơ A, hạn ngày 15/6.", "a"), "Lan", "15/6"),
        (turn("Minh phụ trách hồ sơ B, hạn ngày 17/6.", "b"), "Minh", "17/6"),
    ]
    units, _ = make_graph_units([row[0] for row in data])
    events = [
        validate_event(
            {"kind": "task", "owner": owner, "deadline": date}, unit, {unit.unit_id: unit}
        )
        for unit, (_, owner, date) in zip(units, data, strict=True)
    ]
    graph = build_graph("m", units, events, topics(2), [])
    claim_ids = [event.event_id for event in events]
    packet = packet_for(graph, claim_ids, use_graph=True, soft=False)
    altered = "Lan phụ trách hồ sơ A, hạn ngày 17/6. Minh phụ trách hồ sơ B, hạn ngày 15/6."
    assert not deterministic_risks(altered, " ".join(unit.original for unit in units))
    paragraph = Paragraph(
        text=altered, claim_ids=claim_ids, evidence_ids=[u.unit_id for u in units]
    )
    checks = verify_paragraphs(None, [paragraph], packet)
    assert checks[0]["verdict"] == "deterministic_rejected"
    assert set(checks[0]["risks"]) == {
        "deadline_actor_mismatch:Lan",
        "deadline_actor_mismatch:Minh",
    }


def test_style_scope_is_applied_and_learning_requires_verified_claims():
    from meeting_pipeline.minutes.style_memory import preserves_reviewed_claims, scoped_instructions

    style = default_style()
    assert "task" not in {row["scope"] for row in scoped_instructions(style, "s1", {"proposal"})}
    assert "task" in {row["scope"] for row in scoped_instructions(style, "s2", {"task"})}
    text = "Lan sẽ gửi hồ sơ."
    plan = {
        "schema_version": "3.0",
        "sections": [
            {
                "paragraphs": [
                    {
                        "text": text,
                        "claim_ids": ["c"],
                        "verification": "checked",
                        "alignments": [{"claim_id": "c", "start_char": 0, "end_char": len(text)}],
                    }
                ]
            }
        ],
    }
    assert preserves_reviewed_claims("1. " + text, text, plan)
    assert not preserves_reviewed_claims(text, "Lan đã gửi hồ sơ.", plan)
    assert not preserves_reviewed_claims("1. " + text, text, {"schema_version": "2.0"})


def test_revised_outline_moves_items_and_preserves_unmodified_sections():
    from meeting_pipeline.minutes.graph_contracts import Paragraph
    from meeting_pipeline.minutes.graph_plan import ContentPlan, PlannedSectionEdit, revise_plan

    units, _ = make_graph_units(
        [
            turn("Bản A dùng kho chung.", "a"),
            turn("Bản B còn cần rà soát.", "b"),
            turn("Nhóm gửi tiến độ định kỳ.", "c"),
        ]
    )
    graph = build_graph(
        "m",
        units,
        [fallback_event(unit) for unit in units],
        topics(3, [[1, 0, 0], [0, 1, 0], [0, 0, 1]]),
        [],
        metadata={"transcript_version_id": "t1"},
    )
    sections, ledger = plan_sections(graph)
    assert len(sections) == 3
    for section in sections:
        section.paragraphs = [Paragraph(text=section.outline[0].text, claim_ids=section.claim_ids)]
    plan = ContentPlan(
        graph_id=graph.graph_id,
        transcript_version_id="t1",
        phase="written",
        sections=sections,
        ledger=ledger,
    )
    plan.seal()
    first, second, third = sections
    first_id, second_id, third_id = (section.claim_ids[0] for section in sections)
    edits = [
        PlannedSectionEdit.model_validate(row)
        for row in [
            {
                "section_id": first.section_id,
                "title": "Dự thảo",
                "items": [
                    {"item_id": second_id, "priority": "required", "included": True},
                    {"item_id": first_id, "priority": "optional", "included": False},
                ],
            },
            {"section_id": second.section_id, "title": second.title, "items": []},
            {
                "section_id": third.section_id,
                "title": third.title,
                "items": [
                    {"item_id": third_id, "priority": "optional", "included": True},
                ],
            },
        ]
    ]
    revised, changed = revise_plan(plan, graph, edits)
    assert revised.parent_plan_id == plan.plan_id
    assert revised.plan_id != plan.plan_id
    assert changed == {first.section_id, second.section_id}
    assert revised.sections[0].claim_ids == [second_id]
    assert revised.sections[0].title_edited
    assert revised.sections[2].paragraphs == third.paragraphs
    assert (
        next(row for row in revised.ledger if row["claim_id"] == first_id)["reason"]
        == "outline_edit"
    )
    assert plan.sections[0].claim_ids == [first_id]


def test_request_aliases_do_not_change_source_text_and_roundtrip_ids():
    original = {"unit_id": "stable123", "text": "stable123", "unit_ids": ["stable123"]}
    local = remap_identifiers(original, {"stable123": "u0"})
    assert local["unit_id"] == "u0" and local["text"] == "stable123"
    assert remap_identifiers(local, {"u0": "stable123"}) == original


def test_discourse_links_do_not_pull_whole_long_meeting_into_each_packet():
    units, _ = make_graph_units([turn("Nội dung " + str(i), str(i)) for i in range(30)])
    events = [fallback_event(u) for u in units]
    relations = [
        {
            "source": events[i].event_id,
            "target": events[i - 1].event_id,
            "kind": "refers_to",
            "evidence_ids": [units[i].unit_id, units[i - 1].unit_id],
        }
        for i in range(1, len(units))
    ]
    graph = build_graph("m", units, events, topics(len(units)), relations)
    packet = packet_for(graph, [events[-1].event_id], use_graph=True, soft=False)
    assert len(packet["sources"]) <= 4
    assert len(graph.events) == 30


def test_completion_guard_does_not_transfer_completion_between_actors():
    from meeting_pipeline.minutes.graph_writer import completion_risks

    rows = [
        {"speaker": "Đoan", "text": "Đã đặt biển thử."},
        {"speaker": "Lễ", "text": "Hưng phác cách đặt sau khi có ghi nhận của Đoan."},
    ]
    assert completion_risks("Đoan đã đặt biển thử.", rows) == []
    risks = completion_risks(
        "Sau ghi nhận của Đoan, Hưng đã phác cách đặt.",
        [*rows, {"speaker": "Hưng", "text": "Tôi đề nghị xem lại vị trí."}],
    )
    assert any("Hưng" in risk for risk in risks)
    assert not any("Đoan" in risk for risk in risks)


def test_numeric_guard_allows_equivalent_vietnamese_dates_and_rejects_changed_values():
    from meeting_pipeline.minutes.graph_writer import deterministic_risks

    source = "An gửi hai mươi hồ sơ trước ngày mười hai tháng mười. Có ba phiếu tán thành."
    assert not deterministic_risks(
        "An gửi 20 hồ sơ trước ngày 12/10. Có 3 phiếu tán thành.", source
    )
    assert deterministic_risks("An gửi 200 hồ sơ trước ngày 12/10.", source)
    assert deterministic_risks("An gửi 20 hồ sơ trước ngày 15/10.", source)
