"""Identity and role regressions independent of local meeting artifacts."""

from __future__ import annotations

import json
import unicodedata
from dataclasses import replace
from pathlib import Path

import pytest

from meeting_pipeline.domain.speaker_identity import person_identity_key
from meeting_pipeline.minutes.evidence_retrieval import IndexedTurn, load_indexed_turns
from meeting_pipeline.minutes.fact_extractor import M2RuleFactExtractor
from meeting_pipeline.minutes.schemas import (
    FactStatus,
    SemanticFieldType,
    TemplateField,
    TemplateSchema,
)


def _turn(name: str, speaker_id: str | None, meeting_id: str | None = None) -> IndexedTurn:
    return IndexedTurn(
        turn_id=f"turn-{meeting_id or name}",
        speaker_label=name,
        speaker_id=speaker_id,
        start_sec=0.0,
        end_sec=3.0,
        text="Thông tin cuộc họp",
        tokens=["thông", "tin"],
        source_id="source-1",
        clip_path=None,
        asr_status="transcribed",
        needs_review=False,
        confidence=None,
        meeting_speaker_id=meeting_id,
        speaker_status="identified",
    )


def _facts(turns: list[IndexedTurn], metadata: dict | None = None) -> dict:
    schema = TemplateSchema(
        template_id="people",
        template_name="People",
        template_hash="fixture",
        fields=[
            TemplateField(
                field_id="attendees",
                anchor_id="a1",
                raw_label="Thành phần",
                semantic_type=SemanticFieldType.ATTENDEE_LIST,
            ),
            TemplateField(
                field_id="chair",
                anchor_id="a2",
                raw_label="Chủ trì",
                semantic_type=SemanticFieldType.PERSON_NAME,
            ),
            TemplateField(
                field_id="secretary",
                anchor_id="a3",
                raw_label="Thư ký",
                semantic_type=SemanticFieldType.PERSON_NAME,
            ),
        ],
    )
    return {
        f.field_id: f
        for f in M2RuleFactExtractor().extract_facts(
            schema,
            turns,
            meeting_metadata=metadata,
        )
    }


@pytest.mark.parametrize("label", ["Chưa xác định", "chưa rõ", "Nói chồng", "unknown"])
def test_state_labels_are_never_people_even_with_ids(label: str) -> None:
    assert person_identity_key(label, "profile-1", "ms-1") is None


def test_attendees_deduplicate_profile_aliases_and_exclude_states() -> None:
    turns = [
        _turn("Minh", "minh", "ms-1"),
        replace(_turn("  Anh Minh  ", "minh", "ms-4"), start_sec=4.0),
        _turn("Lan", "lan", "ms-2"),
        _turn("Chưa xác định", None, "bad-1"),
        replace(_turn("Nói chồng", None, "bad-2"), speaker_count=2, overlap_group_id="ov-1"),
    ]
    fact = _facts(turns)["attendees"]
    assert fact.value == ["Anh Minh", "Lan"]
    assert fact.status == FactStatus.NEEDS_REVIEW
    assert {ref.turn_id for ref in fact.evidence_refs} == {"turn-ms-4", "turn-ms-2"}


def test_same_display_name_does_not_merge_different_people() -> None:
    fact = _facts([_turn("Minh", "minh-1"), _turn("Minh", "minh-2")])["attendees"]
    assert fact.value == ["Minh", "Minh"]
    assert len(fact.evidence_refs) == 2


def test_legacy_names_normalize_unicode_whitespace_and_case() -> None:
    first = _turn("Thiện", None)
    second = replace(_turn(unicodedata.normalize("NFD", "  thiện  "), None), start_sec=5)
    assert len(_facts([first, second])["attendees"].value) == 1


def test_numbered_anonymous_people_remain_distinct() -> None:
    turns = [
        replace(_turn(f"Người lạ {i}", None, f"ms-{i}"), speaker_status="anonymous") for i in (1, 2)
    ]
    assert _facts(turns)["attendees"].value == ["Người lạ 1", "Người lạ 2"]


def test_roles_require_explicit_evidence_instead_of_name_order() -> None:
    turns = [_turn("Huy", "huy"), _turn("Lan", "lan"), _turn("Minh", "minh")]
    assert _facts(turns)["chair"].status == FactStatus.UNKNOWN
    assert _facts(turns)["secretary"].status == FactStatus.UNKNOWN
    turns[0] = replace(turns[0], text="Anh Minh là chủ trì. Thư ký là chị Lan.")
    facts = _facts(turns)
    assert facts["chair"].value == "Minh"
    assert facts["secretary"].value == "Lan"
    assert facts["chair"].evidence_refs[0].turn_id == "turn-Huy"


@pytest.mark.parametrize(
    "text",
    [
        "Tôi đề xuất Minh làm chủ trì",
        "Chưa chốt chủ trì là Minh",
        "Không phân công chủ trì là Minh",
        "Chưa có chủ trì là Minh",
    ],
)
def test_proposed_or_negated_role_remains_unknown(text: str) -> None:
    assert _facts([replace(_turn("Minh", "minh"), text=text)])["chair"].value is None


def test_metadata_can_supply_confirmed_participants_and_roles() -> None:
    facts = _facts([], {"chair": "Minh", "attendees": ["Minh", "Lan"]})
    assert facts["chair"].status == FactStatus.SUPPORTED
    assert facts["attendees"].value == ["Minh", "Lan"]


def test_loader_preserves_identity_and_state_separately(tmp_path: Path) -> None:
    (tmp_path / "timeline.json").write_text(
        json.dumps(
            {
                "segments": [
                    {
                        "turn_id": "t1",
                        "speaker_label": "Người lạ 1",
                        "meeting_speaker_id": "ms-1",
                        "speaker_status": "anonymous",
                        "start_sec": 0,
                        "end_sec": 1,
                    },
                    {
                        "turn_id": "t2",
                        "speaker_label": "Nói chồng",
                        "speaker_count": 2,
                        "overlap_group_id": "ov-1",
                        "speaker_status": "ambiguous",
                        "start_sec": 1,
                        "end_sec": 2,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    turns = load_indexed_turns(tmp_path)
    assert turns[0].speaker_id is None
    assert turns[0].meeting_speaker_id == "ms-1"
    assert turns[0].speaker_status == "anonymous"
    assert turns[1].speaker_count == 2
    assert turns[1].overlap_group_id == "ov-1"
