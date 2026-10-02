"""Boundary tests use known activity masks, independent of the diarization code."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np

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
