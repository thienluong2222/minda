"""Regression cases for real word loss, seam drift and genuine repeated speech."""

from __future__ import annotations

import pytest

from meeting_pipeline.adapters.phowhisper_asr import AsrResult
from meeting_pipeline.asr.boundary_words import (
    DecodedChunk,
    filter_boundary_words,
    reconcile_internal_chunks,
)
from meeting_pipeline.domain.contracts import SourceHypothesis
from meeting_pipeline.domain.transcription import TimedWord


def _result(tokens: list[tuple[str, float, float]], offset: float = 0) -> AsrResult:
    return AsrResult(
        text=" ".join(text for text, _, _ in tokens),
        words=[
            TimedWord(text=text, start_sec=start - offset, end_sec=end - offset)
            for text, start, end in tokens
        ],
        status="transcribed",
    )


@pytest.mark.parametrize(
    ("core", "clip", "tokens", "expected"),
    [
        ((2.55, 4.15), (1.8, 4.9), [("trở", 1.8, 3.14)], ["trở"]),
        ((6.6, 8.85), (5.85, 9.6), [("cũng", 5.85, 7.17), ("dặt", 8.39, 9.55)], ["cũng", "dặt"]),
        ((0.3, 8.75), (0, 9.5), [("bộ", 8.64, 9.48)], ["bộ"]),
        ((9.5, 16.6), (8.75, 17.35), [("vắng", 16.33, 17.33)], ["vắng"]),
        ((17.4, 25.7), (16.65, 26.1), [("chỗ", 25.41, 26.07)], ["chỗ"]),
    ],
)
def test_real_outer_boundary_words_are_retained(core, clip, tokens, expected) -> None:
    words, audit = filter_boundary_words(
        _result(tokens, clip[0]), turn_id="turn", core=core, clip=clip
    )
    assert [word.word for word in words] == expected
    assert all(word.time_status == "uncertain" for word in words)
    assert [word.start_sec for word in words] == [start for _, start, _ in tokens]
    assert [word.end_sec for word in words] == [end for _, _, end in tokens]
    assert all(record["reason"] == "outer_boundary_intersection" for record in audit)


def test_context_only_and_invalid_timestamps_are_not_restored() -> None:
    result = _result(
        [
            ("ngữ", 0.1, 0.3),
            ("cảnh", 0.3, 0.5),
            ("giữ", 0.8, 1.1),
            ("suybiến", 1.2, 1.2),
            ("quáclip", 2.1, 3.1),
        ]
    )
    words, audit = filter_boundary_words(result, turn_id="t", core=(0.75, 2), clip=(0, 3))
    assert [word.word for word in words] == ["giữ"]
    assert [record["reason"] for record in audit] == [
        "outside_core_context",
        "outside_core_context",
        "midpoint_in_core",
        "invalid_timestamp",
        "invalid_timestamp",
    ]


def test_rejected_candidate_never_supplies_recovered_words() -> None:
    result = _result([("ảo", 0.1, 1.4)])
    result.status = "unreliable"
    words, audit = filter_boundary_words(result, turn_id="t", core=(1, 2), clip=(0, 3))
    assert not words
    assert audit[0]["reason"] == "rejected_asr_candidate"


def _chunk(index: int, tokens: list[tuple[str, float, float]]) -> DecodedChunk:
    core = (0.0, 2.0) if index == 0 else (2.0, 4.0)
    clip = (0.0, 2.75) if index == 0 else (1.25, 4.0)
    result = _result(tokens, clip[0])
    words, audit = filter_boundary_words(
        result,
        turn_id=f"t{index}",
        core=core,
        clip=clip,
        internal_start=index == 1,
        internal_end=index == 0,
        end_inclusive=index == 1,
    )
    hypothesis = SourceHypothesis(
        meeting_id="m",
        segment_id=f"t{index}",
        source_id="mic",
        text=" ".join(word.word for word in words),
        words=words,
        word_boundary_audit=audit,
    )
    return (
        {"mic": hypothesis},
        {
            "turn_id": f"t{index}",
            "core_interval": list(core),
            "clip_interval": list(clip),
            "asr_chunk_group_id": "same-turn",
        },
    )


@pytest.mark.parametrize(
    ("left_interval", "right_interval"),
    [
        ((1.75, 2.15), (1.85, 2.25)),  # Both midpoints were independently kept.
        ((1.85, 2.25), (1.75, 2.15)),
    ],  # Both midpoints were independently discarded.
)
def test_timestamp_drift_has_one_owner(left_interval, right_interval) -> None:
    chunks = [_chunk(0, [("ranh", *left_interval)]), _chunk(1, [("ranh", *right_interval)])]
    reconcile_internal_chunks(chunks)
    assert [w.word for sources, _ in chunks for w in sources["mic"].words] == ["ranh"]
    records = [r for sources, _ in chunks for r in sources["mic"].word_boundary_audit]
    assert len({r["owner_turn_id"] for r in records}) == 1
    assert any(r["decision"] == "deduplicated" for r in records)


def test_genuine_repetition_survives_matching_context_duplicates() -> None:
    chunks = [
        _chunk(0, [("không", 1.5, 1.75), ("không", 1.9, 2.1)]),
        _chunk(1, [("không", 1.5, 1.75), ("không", 1.9, 2.1), ("được", 2.2, 2.5)]),
    ]
    reconcile_internal_chunks(chunks)
    assert [w.word for sources, _ in chunks for w in sources["mic"].words] == [
        "không",
        "không",
        "được",
    ]


def test_equal_text_at_different_times_is_not_deduplicated() -> None:
    chunks = [_chunk(0, [("đi", 1.5, 1.7)]), _chunk(1, [("đi", 2.1, 2.3)])]
    reconcile_internal_chunks(chunks)
    assert [w.word for sources, _ in chunks for w in sources["mic"].words] == ["đi", "đi"]


def test_word_seen_only_in_neighbour_context_can_move_to_valid_owner() -> None:
    chunks = [_chunk(0, [("làm", 2.05, 2.3)]), _chunk(1, [("được", 2.4, 2.6)])]
    reconcile_internal_chunks(chunks)
    assert chunks[0][0]["mic"].text == ""
    assert chunks[1][0]["mic"].text == "làm được"
    adopted = chunks[1][0]["mic"].word_boundary_audit[-1]
    assert adopted["origin_turn_id"] == "t0" and adopted["owner_turn_id"] == "t1"
    assert adopted["time_status"] == "uncertain"


def test_rejected_neighbour_is_not_reactivated_to_receive_context() -> None:
    chunks = [_chunk(0, [("làm", 2.05, 2.3)]), _chunk(1, [])]
    chunks[1][0]["mic"].asr_status = "unreliable"
    reconcile_internal_chunks(chunks)
    assert chunks[1][0]["mic"].asr_status == "unreliable"
    assert not chunks[1][0]["mic"].words
    assert chunks[0][0]["mic"].word_boundary_audit[0]["reason"] == "owner_source_unavailable"
    assert "asr_boundary_owner_unresolved" in chunks[0][0]["mic"].asr_warnings


def test_different_groups_and_noncontiguous_cores_cannot_be_reconciled() -> None:
    chunks = [_chunk(0, [("a", 1.8, 2.1)]), _chunk(1, [("a", 1.8, 2.1)])]
    chunks[1][1]["asr_chunk_group_id"] = "different-speaker"
    with pytest.raises(ValueError, match="one ASR chunk group"):
        reconcile_internal_chunks(chunks)
    chunks[1][1]["asr_chunk_group_id"] = "same-turn"
    chunks[1][1]["core_interval"][0] = 2.2
    with pytest.raises(ValueError, match="contiguous"):
        reconcile_internal_chunks(chunks)
