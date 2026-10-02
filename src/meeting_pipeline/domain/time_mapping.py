"""Bidirectional mappings between source-local and meeting time."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AffineTimeMapping:
    """Map decoded source seconds ``u`` to meeting seconds ``t = scale*u + offset``."""

    scale: float
    offset_sec: float

    def __post_init__(self) -> None:
        if self.scale <= 0:
            raise ValueError("Time mapping scale must be positive")

    def source_to_meeting(self, source_sec: float) -> float:
        """Convert source-local seconds to the common meeting clock."""
        return self.scale * source_sec + self.offset_sec

    def meeting_to_source(self, meeting_sec: float) -> float:
        """Convert meeting seconds back to source-local seconds."""
        return (meeting_sec - self.offset_sec) / self.scale


@dataclass(frozen=True, slots=True)
class MappingKnot:
    """A corresponding source/meeting time pair for monotone interpolation."""

    source_sec: float
    meeting_sec: float


@dataclass(frozen=True, slots=True)
class PiecewiseTimeMapping:
    """Monotone piecewise-affine time map used when clock drift changes over time."""

    knots: tuple[MappingKnot, ...]

    def __post_init__(self) -> None:
        if len(self.knots) < 2:
            raise ValueError("Piecewise mapping requires at least two knots")
        for left, right in zip(self.knots, self.knots[1:], strict=False):
            if right.source_sec <= left.source_sec or right.meeting_sec <= left.meeting_sec:
                raise ValueError("Piecewise mapping knots must be strictly monotone")

    def source_to_meeting(self, source_sec: float) -> float:
        """Interpolate source time; endpoints are extrapolated using edge segments."""
        left, right = self._source_segment(source_sec)
        ratio = (source_sec - left.source_sec) / (right.source_sec - left.source_sec)
        return left.meeting_sec + ratio * (right.meeting_sec - left.meeting_sec)

    def meeting_to_source(self, meeting_sec: float) -> float:
        """Invert the monotone interpolation, including endpoint extrapolation."""
        left, right = self._meeting_segment(meeting_sec)
        ratio = (meeting_sec - left.meeting_sec) / (right.meeting_sec - left.meeting_sec)
        return left.source_sec + ratio * (right.source_sec - left.source_sec)

    def _source_segment(self, value: float) -> tuple[MappingKnot, MappingKnot]:
        for left, right in zip(self.knots, self.knots[1:], strict=False):
            if value <= right.source_sec:
                return left, right
        return self.knots[-2], self.knots[-1]

    def _meeting_segment(self, value: float) -> tuple[MappingKnot, MappingKnot]:
        for left, right in zip(self.knots, self.knots[1:], strict=False):
            if value <= right.meeting_sec:
                return left, right
        return self.knots[-2], self.knots[-1]
