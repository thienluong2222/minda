"""Boundary tests use known activity masks, independent of the diarization code."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from meeting_pipeline.domain.contracts import MeetingSegment
from meeting_pipeline.pipeline.speaker_turns import SpeakerTurnDetector


class _Window:
    def __init__(self, duration: float, step: float) -> None:
        self.duration = duration
        self.step = step

    def __getitem__(self, index: int) -> SimpleNamespace:
        return SimpleNamespace(start=index * self.step)


class _Adapter:
    def __init__(self, data: np.ndarray, duration: float, step: float) -> None:
        self.output = SimpleNamespace(data=data, sliding_window=_Window(duration, step))

    def segment_file(self, path: Path) -> SimpleNamespace:
        del path
        return self.output


def _segment(end: float) -> list[MeetingSegment]:
    return [MeetingSegment(meeting_id="m", segment_id="seg_0000", start_sec=0, end_sec=end)]


def test_switch_without_silence_creates_two_turns() -> None:
    # One 3-second VAD region: A ends exactly when B begins.
    data = np.zeros((1, 60, 3), dtype=np.float32)
    data[0, :30, 0] = 1
    data[0, 30:, 1] = 1
    detector = SpeakerTurnDetector(Path("unused"), 1.0, _Adapter(data, 3.0, 1.0))
    turns = detector.detect({"phone-1": Path("unused")}, _segment(3.0), "phone-1", 3.0)

    assert len(turns) == 2
    assert [turn.track_id for turn in turns] == ["local-1", "local-2"]
    assert abs(turns[0].end_sec - turns[1].start_sec) < 0.06
    assert all(turn.speaker_count == 1 for turn in turns)


def test_four_speakers_across_windows_are_not_capped_at_three_total() -> None:
    data = np.zeros((3, 40, 3), dtype=np.float32)
    # Windows [0,2], [1,3], [2,4]. Local channel numbers are permuted.
    data[0, :20, 0] = 1  # A
    data[0, 20:, 1] = 1  # B
    data[1, :20, 2] = 1  # B
    data[1, 20:, 0] = 1  # C
    data[2, :20, 1] = 1  # C
    data[2, 20:, 2] = 1  # D
    detector = SpeakerTurnDetector(Path("unused"), 1.0, _Adapter(data, 2.0, 1.0))
    turns = detector.detect({"phone-1": Path("unused")}, _segment(4.0), "phone-1", 4.0)

    assert len(turns) == 4
    assert len({turn.track_id for turn in turns}) == 4
    assert all(turn.speaker_count == 1 for turn in turns)


def test_local_label_disagreement_across_windows_does_not_fabricate_overlap() -> None:
    # Neither window contains simultaneous speech. At the second window's
    # weak left edge, an extra local label fails matching to the previous one.
    data = np.zeros((2, 80, 3), dtype=np.float32)
    data[0, :, 0] = 1
    data[1, :10, 0] = 1
    data[1, 10:, 1] = 1
    detector = SpeakerTurnDetector(Path("unused"), 1.0, _Adapter(data, 4.0, 1.0))
    turns = detector.detect({"ref": Path("ref")}, _segment(5.0), "ref", 5.0)
    assert turns
    assert all(turn.speaker_count == 1 for turn in turns)
    assert all(turn.overlap_group_id is None for turn in turns)
    assert sum(turn.end_sec - turn.start_sec for turn in turns) == pytest.approx(5.0)


def test_overlap_creates_two_rows_with_same_group() -> None:
    data = np.zeros((1, 40, 3), dtype=np.float32)
    data[0, :, 0] = 1
    data[0, 10:30, 1] = 1
    detector = SpeakerTurnDetector(Path("unused"), 1.0, _Adapter(data, 2.0, 1.0))
    turns = detector.detect({"phone-1": Path("unused")}, _segment(2.0), "phone-1", 2.0)

    overlap = [turn for turn in turns if turn.overlap_group_id]
    assert len(overlap) == 2
    assert overlap[0].overlap_group_id == overlap[1].overlap_group_id
    assert overlap[0].track_id != overlap[1].track_id
    assert abs(overlap[0].start_sec - 0.5) < 0.06
    assert abs(overlap[0].end_sec - 1.5) < 0.06


def test_agreed_overlap_survives_permuted_windows() -> None:
    data = np.zeros((2, 80, 3), dtype=np.float32)
    data[0, :, 0] = 1  # A throughout window [0, 4]
    data[0, 40:, 1] = 1  # B at [2, 4]
    data[1, :, 1] = 1  # A throughout window [1, 5], different channel
    data[1, 20:60, 2] = 1  # B at [2, 4], different channel
    detector = SpeakerTurnDetector(Path("unused"), 1.0, _Adapter(data, 4.0, 1.0))
    turns = detector.detect({"ref": Path("ref")}, _segment(5.0), "ref", 5.0)
    overlap = [turn for turn in turns if turn.speaker_count == 2]
    assert len(overlap) == 2
    assert overlap[0].overlap_group_id == overlap[1].overlap_group_id
    assert overlap[0].start_sec == pytest.approx(2.0, abs=0.06)
    assert overlap[0].end_sec == pytest.approx(4.0, abs=0.06)


def test_segmentation_silence_inside_vad_does_not_create_a_speaker() -> None:
    # A padded VAD region can contain a pause that pyannote correctly marks silent.
    data = np.zeros((1, 60, 3), dtype=np.float32)
    data[0, 10:25, 0] = 1
    data[0, 35:50, 0] = 1
    detector = SpeakerTurnDetector(Path("unused"), 1.0, _Adapter(data, 3.0, 1.0))
    turns = detector.detect({"phone-1": Path("unused")}, _segment(3.0), "phone-1", 3.0)

    assert len(turns) == 2
    assert all(turn.track_id == "local-1" for turn in turns)
    assert all(not turn.track_id.startswith("unresolved") for turn in turns)
    assert turns[0].end_sec <= 1.3
    assert turns[1].start_sec >= 1.7


def test_per_source_activity_is_measured_not_defaulted() -> None:
    reference = np.zeros((1, 40, 3), dtype=np.float32)
    reference[0, :, 0] = 1
    other = np.zeros((1, 40, 3), dtype=np.float32)
    other[0, 10:30, 0] = 1
    other[0, 10:30, 1] = 1

    class PerSourceAdapter:
        def segment_file(self, path: Path, source_id: str = "") -> SimpleNamespace:
            del path
            data = reference if source_id == "ref" else other
            return SimpleNamespace(data=data, sliding_window=_Window(2.0, 1.0))

    detector = SpeakerTurnDetector(Path("unused"), 1.0, PerSourceAdapter())
    turns = detector.detect({"ref": Path("ref"), "other": Path("other")}, _segment(2.0), "ref", 2.0)
    overlap = next(turn for turn in turns if turn.start_sec == 0.5)
    assert overlap.source_activity["ref"]["speech_coverage"] == 1.0
    assert overlap.source_activity["other"]["speech_coverage"] == 1.0
    assert overlap.source_activity["other"]["local_speaker_purity"] == 0.0
    before = next(turn for turn in turns if turn.end_sec == 0.5)
    assert before.source_activity["other"]["speech_coverage"] == 0.0


def test_alignment_failed_source_cannot_create_turn() -> None:
    silent = np.zeros((1, 40, 3), dtype=np.float32)
    loud = silent.copy()
    loud[0, :, 0] = 1.0

    class PerSourceAdapter:
        def segment_file(self, path: Path, source_id: str = "") -> SimpleNamespace:
            del path
            return SimpleNamespace(
                data=silent if source_id == "ref" else loud,
                sliding_window=_Window(2.0, 1.0),
            )

    detector = SpeakerTurnDetector(Path("unused"), 1.0, PerSourceAdapter())
    turns = detector.detect(
        {"ref": Path("ref"), "failed": Path("failed")},
        _segment(2.0),
        "ref",
        2.0,
        sync_metadata={"ref": {"status": "reference"}, "failed": {"status": "alignment_failed"}},
    )
    assert turns == []


@pytest.mark.parametrize("unresolved", [False, True])
def test_brief_dropout_between_same_track_is_bridged(unresolved: bool) -> None:
    reference = np.zeros((1, 60, 3), dtype=np.float32)
    reference[0, 5:55, 0] = 1
    reference[0, 25:31, 0] = 0  # 300ms dropout
    other = reference.copy()
    if unresolved:
        other[0, 25:31, 0] = 1
    detector = SpeakerTurnDetector(Path("unused"), 1.0, _Adapter(reference, 3.0, 1.0))
    scores = {
        "ref": SimpleNamespace(data=reference, sliding_window=_Window(3.0, 1.0)),
        "other": SimpleNamespace(data=other, sliding_window=_Window(3.0, 1.0)),
    }
    turns = detector.detect(
        {"ref": Path("ref"), "other": Path("other")},
        _segment(3.0),
        "ref",
        3.0,
        cached_results=scores,
    )
    assert len(turns) == 1
    assert turns[0].start_sec == 0.25
    assert turns[0].end_sec == 2.75
    assert turns[0].track_id == "local-1"


@pytest.mark.parametrize("reply_bins", [4, 6])
def test_short_real_speaker_is_preserved_and_padding_respects_switches(reply_bins: int) -> None:
    data = np.zeros((1, 60, 3), dtype=np.float32)
    data[0, 5:25, 0] = 1
    boundary_bin = 25 + reply_bins
    data[0, 25:boundary_bin, 1] = 1  # short but genuine reply from B
    data[0, boundary_bin:55, 0] = 1
    detector = SpeakerTurnDetector(
        Path("unused"),
        1.0,
        _Adapter(data, 3.0, 1.0),
        speech_pad_sec=0.25,
    )
    turns = detector.detect({"ref": Path("unused")}, _segment(3.0), "ref", 3.0)
    assert len(turns) == 3
    assert [t.track_id for t in turns] == ["local-1", "local-2", "local-1"]
    assert turns[0].start_sec == 0.0
    assert turns[-1].end_sec == 3.0
    assert turns[0].end_sec == turns[1].start_sec == 1.25
    assert turns[1].end_sec == turns[2].start_sec == round(boundary_bin * 0.05, 3)


def test_padding_shares_silence_without_crossing_other_speaker() -> None:
    data = np.zeros((1, 60, 3), dtype=np.float32)
    data[0, 5:25, 0] = 1
    data[0, 31:55, 1] = 1
    detector = SpeakerTurnDetector(
        Path("unused"),
        1.0,
        _Adapter(data, 3.0, 1.0),
        speech_pad_sec=0.25,
    )
    turns = detector.detect({"ref": Path("unused")}, _segment(3.0), "ref", 3.0)
    assert len(turns) == 2
    assert turns[0].end_sec == turns[1].start_sec == 1.4
