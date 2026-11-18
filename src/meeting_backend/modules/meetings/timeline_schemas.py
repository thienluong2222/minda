"""Versioned, audio-preserving layout contracts shared with the future timeline UI."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}$")]
Milliseconds = Annotated[int, Field(strict=True, ge=0, le=604_800_000)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClockOrigin(Contract):
    iso_time: str = Field(max_length=64)
    origin: Literal["user", "capture_log"] = "user"
    status: Literal["declared", "verified"] = "declared"

    @field_validator("iso_time")
    @classmethod
    def timezone_required(cls, value):
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("Wall-clock origin needs an explicit timezone")
        return parsed.astimezone(UTC).isoformat()


class Anchored(Contract):
    kind: Literal["anchored"] = "anchored"
    start_ms: Annotated[int, Field(strict=True, ge=-604_800_000, le=604_800_000)]
    origin: Literal["user", "capture_log", "audio_match"] = "user"
    status: Literal["declared", "verified", "needs_review"] = "declared"


class Sequential(Contract):
    kind: Literal["sequential"] = "sequential"
    gap_before_ms: Milliseconds | None = None
    after_clip_id: Identifier | None = None
    origin: Literal["unknown", "user", "capture_log", "audio_match"] = "unknown"


Placement = Annotated[Anchored | Sequential, Field(discriminator="kind")]


class Clip(Contract):
    id: Identifier
    asset_id: Identifier
    source_in_ms: Milliseconds = 0
    source_out_ms: Milliseconds
    placement: Placement = Field(default_factory=Sequential)
    timing_history: list[dict] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def positive_range(self):
        if self.source_out_ms <= self.source_in_ms:
            raise ValueError("Audio range must be positive")
        return self


class Track(Contract):
    id: Identifier
    name: str = Field(min_length=1, max_length=100)
    device_id: Identifier | None = None
    clip_ids: list[Identifier] = Field(default_factory=list, max_length=5000)


class Interval(Contract):
    id: Identifier
    kind: Literal["session", "break", "excluded"]
    label: str = Field(default="", max_length=200)
    start_ms: Milliseconds | None = None
    end_ms: Milliseconds | None = None
    start_clip_id: Identifier | None = None
    end_clip_id: Identifier | None = None
    confirmed: bool = False

    @model_validator(mode="after")
    def ordered_bounds(self):
        if self.start_ms is not None and self.end_ms is not None:
            if self.end_ms <= self.start_ms:
                raise ValueError("Interval end must be after its start")
        return self


class Timeline(Contract):
    schema_version: Literal[1] = 1
    alignment_mode: Literal["legacy", "auto"] = "legacy"
    clock_origin: ClockOrigin | None = None
    tracks: list[Track] = Field(default_factory=list, max_length=8)
    clips: list[Clip] = Field(default_factory=list, max_length=5000)
    unassigned_asset_ids: list[Identifier] = Field(default_factory=list, max_length=2000)
    intervals: list[Interval] = Field(default_factory=list, max_length=256)


class CreateTrack(Contract):
    op: Literal["create_track"]
    id: Identifier
    name: str = Field(min_length=1, max_length=100)
    device_id: Identifier | None = None


class UpdateTrack(Contract):
    op: Literal["update_track"]
    track_id: Identifier
    name: str = Field(min_length=1, max_length=100)
    device_id: Identifier | None = None


class ReorderTracks(Contract):
    op: Literal["reorder_tracks"]
    track_ids: list[Identifier] = Field(max_length=8)


class RemoveTrack(Contract):
    op: Literal["remove_track"]
    track_id: Identifier


class AddClip(Contract):
    op: Literal["add_clip"]
    id: Identifier
    track_id: Identifier
    asset_id: Identifier
    source_in_ms: Milliseconds = 0
    source_out_ms: Milliseconds | None = None
    before_clip_id: Identifier | None = None
    placement: Placement = Field(default_factory=Sequential)


class MoveClip(Contract):
    op: Literal["move_clip"]
    clip_id: Identifier
    track_id: Identifier
    before_clip_id: Identifier | None = None
    placement: Placement | None = None


class SetPlacement(Contract):
    op: Literal["set_placement"]
    clip_id: Identifier
    placement: Placement


class SetRange(Contract):
    op: Literal["set_range"]
    clip_id: Identifier
    source_in_ms: Milliseconds
    source_out_ms: Milliseconds


class RemoveClip(Contract):
    op: Literal["remove_clip"]
    clip_id: Identifier


class UpsertInterval(Contract):
    op: Literal["upsert_interval"]
    interval: Interval


class RemoveInterval(Contract):
    op: Literal["remove_interval"]
    interval_id: Identifier


class SetClockOrigin(Contract):
    op: Literal["set_clock_origin"]
    value: ClockOrigin | None


Operation = Annotated[
    CreateTrack
    | UpdateTrack
    | ReorderTracks
    | RemoveTrack
    | AddClip
    | MoveClip
    | SetPlacement
    | SetRange
    | RemoveClip
    | UpsertInterval
    | RemoveInterval
    | SetClockOrigin,
    Field(discriminator="op"),
]


class TimelinePatch(Contract):
    revision: int = Field(ge=1, strict=True)
    operations: list[Operation] = Field(min_length=1, max_length=200)
