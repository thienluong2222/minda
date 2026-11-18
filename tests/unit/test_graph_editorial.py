"""Regressions from the real meeting: names, atomic facts, outline and local repair."""

from types import SimpleNamespace

from test_minutes_graph import make_graph_units, topics, turn

from meeting_pipeline.minutes.graph_builder import (
    build_graph,
    extract_events,
    fallback_event,
    validate_event,
)
from meeting_pipeline.minutes.graph_contracts import Paragraph, default_style
from meeting_pipeline.minutes.graph_editorial import name_topics
from meeting_pipeline.minutes.graph_topics import discover_topics
from meeting_pipeline.minutes.graph_writer import (
    deterministic_risks,
    plan_sections,
    polish_sections,
    write_sections,
)


class Session:
    settings = SimpleNamespace(
        input_token_budget=6144,
        output_token_budget=2048,
        compact_graph_output=True,
        extraction_batch_size=6,
        max_clusters=4,
        fuzziness=1.3,
        minimum_silhouette=0.08,
    )

    def token_count(self, text):
        return len(text.split())

    def embed(self, texts):
        return [[1, 0.1] for _ in texts]


def test_procedural_and_broken_fragments_do_not_become_discussion_topics():
    units, _ = make_graph_units(
        [
            turn("Bắt đầu cuộc họp lúc chín giờ.", "open"),
            turn("An đề nghị chia tài liệu theo năm và chủ đề.", "body"),
            turn("không", "fragment"),
            turn("Tôi không chấp thuận mốc hoàn thành này.", "dissent"),
            turn("Kết quả biểu quyết ba phiếu tán thành.", "vote"),
        ]
    )
    clustered, _ = discover_topics(Session(), units)
    assert clustered["primary"][1] == clustered["primary"][3]
    assert clustered["primary"][0] != clustered["primary"][1]
    events = [fallback_event(unit) for unit in units]
    graph = build_graph("m", units, events, clustered, [])
    sections, ledger = plan_sections(graph)
    assert all(events[2].event_id not in section.claim_ids for section in sections)
    assert any(row.get("needs_review") for row in ledger if row["claim_id"] == events[2].event_id)
    assert any(events[3].event_id in section.claim_ids for section in sections)
    assert any(section.outline for section in sections)
    assert units[2].original == "không"


def test_topic_names_are_independent_and_synchronised_with_outline_and_graph():
    units, _ = make_graph_units([turn("Nhóm tổ chức kho tài liệu theo năm và chủ đề.")])
    events = [fallback_event(units[0])]
    topic = topics(1) | {"titles": ["Vấn đề 1"]}

    class Naming(Session):
        def generate_json(self, system, payload):
            return {"topics": [{"topic_id": 0, "title": "Tổ chức kho tài liệu"}]}

    named = name_topics(Naming(), units, events, topic)
    graph = build_graph("m", units, events, named, [])
    sections, _ = plan_sections(graph)
    assert sections[0].title == "Tổ chức kho tài liệu"
    assert (
        next(node.label for node in graph.nodes if node.node_id == "topic:0") == sections[0].title
    )
    assert sections[0].topic_id == "topic:0"

    class Broken(Session):
        def generate_json(self, system, payload):
            raise ValueError("bad JSON")

    assert not name_topics(Broken(), units, events, topic)["titles"][0].startswith("Vấn đề")


def test_atomic_extraction_preserves_both_assignments_and_all_source_words():
    text = "Lan gửi danh sách trước ngày 5/10 và Huy nhập 20 tài liệu trước ngày 12/10."
    units, _ = make_graph_units([turn(text)])

    class Atomic(Session):
        def generate_json(self, system, payload):
            uid = payload["units"][0]["unit_id"]
            return {
                "items": [
                    [
                        uid,
                        "task",
                        {
                            "text": "Lan gửi danh sách trước ngày 5/10",
                            "owner": "Lan",
                            "deadline": "trước ngày 5/10",
                        },
                    ],
                    [
                        uid,
                        "task",
                        {
                            "text": "và Huy nhập 20 tài liệu trước ngày 12/10.",
                            "owner": "Huy",
                            "deadline": "trước ngày 12/10",
                        },
                    ],
                ]
            }

    events, _, _ = extract_events(Atomic(), units)
    assert len(events) == 2 and len({event.event_id for event in events}) == 2
    assert {event.owner for event in events} == {"Lan", "Huy"}
    assert all(event.extraction == "model" for event in events)

    class Omission(Atomic):
        def generate_json(self, system, payload):
            result = super().generate_json(system, payload)
            result["items"] = result["items"][:1]
            return result

    events, _, _ = extract_events(Omission(), units)
    assert len(events) == 1 and events[0].extraction == "source_fallback"
    assert events[0].text == text


def test_invalid_batch_json_is_retried_without_losing_other_units():
    units, _ = make_graph_units([turn("Lan nhận việc.", "a"), turn("Huy nhận việc.", "b")])

    class Recovery(Session):
        def generate_json_many(self, system, payloads):
            return [ValueError("invalid JSON") for _ in payloads]

        def generate_json(self, system, payload):
            assert payload.get("repair")
            return {"items": [[row["unit_id"], "task"] for row in payload["units"]]}

    events, _, _ = extract_events(Recovery(), units)
    assert len(events) == 2 and all(event.extraction == "model" for event in events)


def test_sentence_repair_keeps_good_sentence_and_room_identity():
    units, _ = make_graph_units([turn("Cuộc họp tại phòng B201 và nhóm có 3 thành viên.")])
    graph = build_graph("m", units, [fallback_event(units[0])], topics(1), [])
    sections, _ = plan_sections(graph)

    class Repair(Session):
        def generate_json(self, system, payload):
            if "Chỉ sửa các câu" in system:
                assert len(payload["sentences"]) == 1
                return {
                    "patches": [
                        {
                            "paragraph_index": 0,
                            "sentence_index": 0,
                            "text": "Cuộc họp tại phòng B201.",
                        }
                    ]
                }
            if "Kiểm tra từng đoạn" in system:
                claim = payload["claims"][0]
                return {
                    "checks": [
                        {
                            "paragraph_index": 0,
                            "verdict": "supported",
                            "assertions": [
                                {
                                    "claim_id": claim["claim_id"],
                                    "fragment": i,
                                    "evidence_ids": claim["unit_ids"],
                                }
                                for i in range(len(payload["paragraphs"][0]["fragments"]))
                            ],
                        }
                    ]
                }
            return {"text": "Cuộc họp tại phòng B211. Nhóm có 3 thành viên."}

    sections, audit = write_sections(Repair(), graph, sections)
    assert sections[0].paragraphs[0].text == "Cuộc họp tại phòng B201. Nhóm có 3 thành viên."
    assert sections[0].paragraphs[0].verification == "checked"
    assert any(row["action"] == "sentence_repair" for row in audit)


def test_fallback_punctuation_and_neutral_attribution():
    from meeting_pipeline.minutes.graph_editorial import readable_source
    from meeting_pipeline.minutes.graph_writer import deterministic_risks

    assert readable_source("Đúng, chưa chốt ngày tập hợp;") == "Đúng, chưa chốt ngày tập hợp."
    assert readable_source("Bao giờ họp lại?") == "Bao giờ họp lại?"
    assert "unsupported_objection" in deterministic_risks(
        "Lợi phản bác phương án.", "Lợi nói lịch chưa xác định ngày."
    )
    assert deterministic_risks("Người lạ 1 gửi 20 hồ sơ.", "gửi 20 hồ sơ.") == []
    assert deterministic_risks("Phòng B211.", "Phòng B201.")


def test_failed_final_polish_keeps_previously_accepted_paragraphs():
    units, _ = make_graph_units([turn("Lan gửi hồ sơ.", "a"), turn("Huy rà tài liệu.", "b")])
    events = [fallback_event(unit) for unit in units]
    graph = build_graph("m", units, events, topics(2), [])
    sections, _ = plan_sections(graph)
    sections[0].paragraphs = [
        Paragraph(
            text=e.text, claim_ids=[e.event_id], evidence_ids=e.unit_ids, verification="checked"
        )
        for e in events
    ]
    before = [p.model_dump() for p in sections[0].paragraphs]

    class BadPolish(Session):
        def generate_json(self, system, payload):
            return {"paragraphs": []}

    audit = polish_sections(BadPolish(), graph, sections, default_style())
    assert audit[0]["action"] == "polish_kept_draft"
    assert [p.model_dump() for p in sections[0].paragraphs] == before


def test_final_polish_can_join_checked_paragraphs_with_all_claims_and_sources():
    units, _ = make_graph_units([turn("Lan gửi hồ sơ.", "a"), turn("Huy rà tài liệu.", "b")])
    events = [fallback_event(unit) for unit in units]
    graph = build_graph("m", units, events, topics(2), [])
    sections, _ = plan_sections(graph)
    sections[0].paragraphs = [
        Paragraph(
            text=e.text, claim_ids=[e.event_id], evidence_ids=e.unit_ids, verification="checked"
        )
        for e in events
    ]

    class GoodPolish(Session):
        def generate_json(self, system, payload):
            if "Kiểm tra từng đoạn" in system:
                return {
                    "checks": [
                        {
                            "paragraph_index": 0,
                            "verdict": "supported",
                            "assertions": [
                                {
                                    "claim_id": claim["claim_id"],
                                    "fragment": 0,
                                    "evidence_ids": claim["unit_ids"],
                                }
                                for claim in payload["claims"]
                            ],
                        }
                    ]
                }
            return {
                "paragraphs": [
                    {
                        "text": "Lan gửi hồ sơ, còn Huy rà tài liệu.",
                        "claim_ids": [row["claim_id"] for row in payload["claims"]],
                    }
                ]
            }

    audit = polish_sections(GoodPolish(), graph, sections, default_style())
    assert audit[0]["action"] == "polish_accepted"
    assert set(sections[0].paragraphs[0].claim_ids) == {e.event_id for e in events}
    assert set(sections[0].paragraphs[0].evidence_ids) == {u.unit_id for u in units}


def test_clause_segmentation_keeps_condition_scope_and_exact_source_offsets():
    source = turn(
        "tôi xác nhận sẽ gửi danh sách tôi cũng đề nghị kiểm tra quyền trước khi nhập",
        speaker="Lan",
    )
    units, _ = make_graph_units([source])
    assert len(units) == 2
    assert " ".join(unit.original for unit in units) == source.text
    assert all(
        source.text[u.sources[0].start_char : u.sources[0].end_char] == u.original for u in units
    )
    condition = turn(
        "nếu Lan gửi danh sách trước ngày 5/10 tôi sẽ nhập 20 tài liệu trước ngày 12/10",
        speaker="Huy",
    )
    units, _ = make_graph_units([condition])
    assert len(units) == 1 and "nếu" in units[0].original


def test_unknown_speaker_or_concluding_a_group_plan_does_not_establish_owner():
    unit = make_graph_units(
        [turn("tôi kết luận nhóm sẽ thực hiện phương án đã chốt", speaker="Minh")]
    )[0][0]
    event = validate_event({"kind": "decision", "owner": "Minh"}, unit, {unit.unit_id: unit})
    assert event.owner is None
    unit = make_graph_units([turn("tôi sẽ gửi danh sách", speaker="Người lạ 2")])[0][0]
    event = validate_event({"kind": "task", "owner": "Người lạ 2"}, unit, {unit.unit_id: unit})
    assert event.owner is None


def test_vote_ratios_and_spoken_room_codes_keep_typed_values():
    from meeting_pipeline.minutes.graph_values import canonical_values

    source = "Tổng số ba phiếu, ba phiếu tán thành, không có phiếu không tán thành."
    assert canonical_values("3/3 phiếu tán thành, 0 phiếu phản đối.") == canonical_values(source)
    assert canonical_values("2/3 phiếu tán thành, 0 phiếu phản đối.") != canonical_values(source)
    assert canonical_values("phòng bê hai không một") == canonical_values("phòng B201")
    assert canonical_values("phòng B201") != canonical_values("phòng C201")


def test_graph_refinement_only_moves_fuzzy_candidates_with_supported_relations():
    from meeting_pipeline.minutes.graph_contracts import GraphEdge
    from meeting_pipeline.minutes.graph_topics import refine_topics

    units, _ = make_graph_units([turn(f"Đoạn nội dung {i}.", str(i)) for i in range(4)])
    events = [fallback_event(unit) for unit in units]
    initial = topics(4, [[0.51, 0.49], [0.1, 0.9], [0.9, 0.1], [1.0, 0.0]])
    initial["unit_roles"] = ["discussion", "discussion", "discussion", "opening"]
    edge = GraphEdge(
        source=events[0].event_id,
        target=events[1].event_id,
        kind="opposes",
        evidence_ids=[units[0].unit_id, units[1].unit_id],
    )
    result = refine_topics(initial, units, events, [edge])
    assert result["primary"][0] == result["primary"][1]
    assert result["primary"][3] == initial["primary"][3]
    assert result["graph_refinement"]["reassigned_units"] == 1
    candidate = edge.model_copy(update={"asserted": False})
    assert refine_topics(initial, units, events, [candidate])["primary"] == initial["primary"]


def test_generation_does_not_receive_unrelated_meeting_context():
    from meeting_pipeline.minutes.graph_writer import packet_for, writing_packet

    units, _ = make_graph_units(
        [turn("Nhóm có 3 thành viên.", "a"), turn("Lan gửi 20 hồ sơ.", "b")]
    )
    events = [fallback_event(unit) for unit in units]
    graph = build_graph("m", units, events, topics(2), [])
    packet = packet_for(graph, [events[1].event_id], use_graph=True, soft=True)
    assert len(packet["sources"]) == 2
    generation = writing_packet(graph, packet, [events[1].event_id])
    assert [row["source_text"] for row in generation["claims"]] == ["Lan gửi 20 hồ sơ."]
    assert len(generation["sources"]) == 1
    assert "Nhóm có 3 thành viên" not in str(generation)


def test_short_meeting_outline_combines_fuzzy_clusters_without_losing_tasks_or_vote():
    units, _ = make_graph_units(
        [
            turn("Bắt đầu cuộc họp về việc triển khai kho tài liệu nội bộ.", "a"),
            turn("Nhóm đề xuất chia tài liệu theo năm.", "b"),
            turn("Lan gửi danh sách.", "c"),
            turn("Huy nhập tài liệu.", "d"),
            turn("Kết quả biểu quyết ba phiếu tán thành.", "e"),
        ]
    )
    events = [fallback_event(unit) for unit in units]
    events[1].kind = "proposal"
    events[2].kind = events[3].kind = "task"
    events[4].kind = "vote"
    clustered = topics(5, [[1, 0, 0], [1, 0, 0], [0, 1, 0], [0, 1, 0], [0, 0, 1]])
    graph = build_graph("m", units, events, clustered, [])
    sections, ledger = plan_sections(graph, editorial_layout=True)
    assert [section.title for section in sections] == [
        "Triển khai kho tài liệu nội bộ",
        "Phân công thực hiện",
        "Kết quả biểu quyết",
    ]
    assert {cid for section in sections for cid in section.claim_ids} == {
        event.event_id for event in events[1:]
    }
    assert all(
        row.get("section_id") in {"discussion", "tasks", "voting"}
        for row in ledger
        if row["disposition"] == "included"
    )


def test_date_only_topic_names_are_repaired_as_descriptive_labels():
    units, _ = make_graph_units([turn("Hoàn thành tài liệu trước ngày mười hai tháng mười.")])
    events = [fallback_event(units[0])]

    class LabelRepair(Session):
        calls = 0

        def generate_json(self, system, payload):
            self.calls += 1
            return {
                "topics": [
                    {
                        "topic_id": 0,
                        "title": "Mười hai tháng mười"
                        if self.calls == 1
                        else "Tiến độ hoàn thành tài liệu",
                    }
                ]
            }

    session = LabelRepair()
    result = name_topics(session, units, events, topics(1))
    assert session.calls == 2
    assert result["titles"] == ["Tiến độ hoàn thành tài liệu"]


def test_rejecting_old_date_does_not_cancel_an_entire_conditional_alternative():
    units, _ = make_graph_units(
        [
            turn("Đề xuất ngày 6/10; nếu gửi trước ngày 5/10 thì hoàn tất trước ngày 12/10.", "a"),
            turn("Nhóm quyết định không dùng mốc hoàn thành ngày 6/10.", "b"),
        ]
    )
    # One quoted claim can still contain multiple alternative dates. A transition
    # about only 6/10 cannot mark the whole conditional 5/10 -> 12/10 as superseded.
    from meeting_pipeline.minutes.graph_contracts import GraphUnit

    combined = GraphUnit(
        unit_id="multi",
        turn_id="a",
        original="Đề xuất ngày 6/10; nếu gửi trước ngày 5/10 thì hoàn tất trước ngày 12/10.",
        text="Đề xuất ngày 6/10; nếu gửi trước ngày 5/10 thì hoàn tất trước ngày 12/10.",
    )
    units = [combined, units[-1]]
    events = [fallback_event(unit) for unit in units]
    events[0].kind = "proposal"
    events[0].lifecycle = "proposed"
    events[1].kind = "decision"
    graph = build_graph(
        "m",
        units,
        events,
        topics(2),
        [
            {
                "source": events[1].event_id,
                "target": events[0].event_id,
                "kind": "supersedes",
                "evidence_ids": [unit.unit_id for unit in units],
            }
        ],
    )
    assert graph.events[0].lifecycle == "proposed"
    assert any(edge.kind == "refers_to" and not edge.asserted for edge in graph.edges)
