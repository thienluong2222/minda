"""Unit tests for multi-source VAD fusion and activity detection."""

from __future__ import annotations

from meeting_pipeline.pipeline.stages.activity_detection import fuse_vad_intervals


def test_merge_gap_close_regions() -> None:
    """Two speech regions 300 ms apart are merged when merge_gap_ms=400."""
    source_intervals = {
        "src-1": [(1.0, 2.0), (2.3, 3.5)],
    }
    source_coverages = {"src-1": (0.0, 10.0)}
    valid_source_ids = ["src-1"]

    regions = fuse_vad_intervals(
        source_intervals=source_intervals,
        source_coverages=source_coverages,
        valid_source_ids=valid_source_ids,
        meeting_duration=10.0,
        merge_gap_ms=400,
        minimum_speech_ms=250,
        speech_pad_ms=0,
    )

    assert len(regions) == 1
    assert abs(regions[0].start_sec - 1.0) < 0.05
    assert abs(regions[0].end_sec - 3.5) < 0.05


def test_merge_gap_far_regions() -> None:
    """Two speech regions 500 ms apart are NOT merged when merge_gap_ms=400."""
    source_intervals = {
        "src-1": [(1.0, 2.0), (2.5, 3.5)],
    }
    source_coverages = {"src-1": (0.0, 10.0)}
    valid_source_ids = ["src-1"]

    regions = fuse_vad_intervals(
        source_intervals=source_intervals,
        source_coverages=source_coverages,
        valid_source_ids=valid_source_ids,
        meeting_duration=10.0,
        merge_gap_ms=400,
        minimum_speech_ms=250,
        speech_pad_ms=0,
    )

    assert len(regions) == 2
    assert abs(regions[0].start_sec - 1.0) < 0.05
    assert abs(regions[0].end_sec - 2.0) < 0.05
    assert abs(regions[1].start_sec - 2.5) < 0.05
    assert abs(regions[1].end_sec - 3.5) < 0.05


def test_minimum_speech_filtered() -> None:
    """A region shorter than minimum_speech_ms (150 ms < 250 ms) is discarded."""
    source_intervals = {
        "src-1": [(1.0, 1.15)],
    }
    source_coverages = {"src-1": (0.0, 10.0)}
    valid_source_ids = ["src-1"]

    regions = fuse_vad_intervals(
        source_intervals=source_intervals,
        source_coverages=source_coverages,
        valid_source_ids=valid_source_ids,
        meeting_duration=10.0,
        minimum_speech_ms=250,
        speech_pad_ms=0,
    )

    assert len(regions) == 0


def test_padding_non_negative() -> None:
    """Speech padding at time 0.1s does not produce negative timestamps."""
    source_intervals = {
        "src-1": [(0.1, 1.0)],
    }
    source_coverages = {"src-1": (0.0, 10.0)}
    valid_source_ids = ["src-1"]

    regions = fuse_vad_intervals(
        source_intervals=source_intervals,
        source_coverages=source_coverages,
        valid_source_ids=valid_source_ids,
        meeting_duration=10.0,
        speech_pad_ms=250,
    )

    assert len(regions) == 1
    assert regions[0].start_sec == 0.0
    assert regions[0].end_sec > 1.0


def test_padding_clamp_meeting_duration() -> None:
    """Speech padding at end does not exceed meeting duration."""
    source_intervals = {
        "src-1": [(8.0, 9.9)],
    }
    source_coverages = {"src-1": (0.0, 10.0)}
    valid_source_ids = ["src-1"]

    regions = fuse_vad_intervals(
        source_intervals=source_intervals,
        source_coverages=source_coverages,
        valid_source_ids=valid_source_ids,
        meeting_duration=10.0,
        speech_pad_ms=250,
    )

    assert len(regions) == 1
    assert regions[0].end_sec == 10.0


def test_invalid_source_excluded() -> None:
    """Sources not in valid_source_ids are completely excluded from fusion."""
    source_intervals = {
        "src-valid": [(2.0, 4.0)],
        "src-invalid": [(6.0, 8.0)],
    }
    source_coverages = {
        "src-valid": (0.0, 10.0),
        "src-invalid": (0.0, 10.0),
    }
    # src-invalid is excluded (e.g. alignment_failed)
    valid_source_ids = ["src-valid"]

    regions = fuse_vad_intervals(
        source_intervals=source_intervals,
        source_coverages=source_coverages,
        valid_source_ids=valid_source_ids,
        meeting_duration=10.0,
        speech_pad_ms=0,
    )

    assert len(regions) == 1
    assert abs(regions[0].start_sec - 2.0) < 0.05
    assert abs(regions[0].end_sec - 4.0) < 0.05
    assert regions[0].supporting_source_ids == ["src-valid"]


def test_outside_coverage_not_silence() -> None:
    """Zero padding / silence outside source coverage is not treated as non-speech vote."""
    source_intervals = {
        "src-1": [(2.0, 4.0)],
    }
    source_coverages = {
        "src-1": (1.0, 5.0),
        "src-2": (4.0, 10.0),
    }
    valid_source_ids = ["src-1", "src-2"]

    regions = fuse_vad_intervals(
        source_intervals=source_intervals,
        source_coverages=source_coverages,
        valid_source_ids=valid_source_ids,
        meeting_duration=10.0,
        speech_pad_ms=0,
    )

    assert len(regions) == 1
    assert regions[0].supporting_source_ids == ["src-1"]


def test_supporting_source_ids_and_warnings() -> None:
    """Warning single_source_vad_support is added when only 1 source supports.

    Other sources have coverage but did not detect speech.
    """
    source_intervals = {
        "src-1": [(2.0, 4.0)],
        "src-2": [],
    }
    source_coverages = {
        "src-1": (0.0, 10.0),
        "src-2": (0.0, 10.0),
    }
    valid_source_ids = ["src-1", "src-2"]

    regions = fuse_vad_intervals(
        source_intervals=source_intervals,
        source_coverages=source_coverages,
        valid_source_ids=valid_source_ids,
        meeting_duration=10.0,
        speech_pad_ms=0,
    )

    assert len(regions) == 1
    assert regions[0].supporting_source_ids == ["src-1"]
    assert "single_source_vad_support" in regions[0].warnings
