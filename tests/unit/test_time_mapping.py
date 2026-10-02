import pytest

from meeting_pipeline.domain.time_mapping import (
    AffineTimeMapping,
    MappingKnot,
    PiecewiseTimeMapping,
)


def test_affine_round_trip_with_drift_and_negative_offset() -> None:
    mapping = AffineTimeMapping(scale=1.0002, offset_sec=-2.5)
    for source_sec in (0.0, 1.0, 123.456):
        assert mapping.meeting_to_source(mapping.source_to_meeting(source_sec)) == pytest.approx(
            source_sec
        )


def test_piecewise_round_trip_across_boundary() -> None:
    mapping = PiecewiseTimeMapping(
        knots=(MappingKnot(0, 1), MappingKnot(10, 11), MappingKnot(20, 21.01))
    )
    for source_sec in (0, 5, 10, 15, 20):
        assert mapping.meeting_to_source(mapping.source_to_meeting(source_sec)) == pytest.approx(
            source_sec
        )
