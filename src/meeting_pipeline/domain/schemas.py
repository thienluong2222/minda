"""Versioned contracts shared by CLI, worker, pipeline and web."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator

NonNegativeFloat = Annotated[float, Field(ge=0)]
PositiveFloat = Annotated[float, Field(gt=0)]


class RunStatus(StrEnum):
    """Persisted lifecycle states for an immutable run."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class SpeakerStatus(StrEnum):
    """Outcome of open-set speaker identity matching."""

    IDENTIFIED = "identified"
    UNKNOWN = "unknown"
    AMBIGUOUS = "ambiguous"


class Interval(BaseModel):
    """Half-open interval ``[start_sec, end_sec)`` on a documented time axis."""

    start_sec: NonNegativeFloat
    end_sec: PositiveFloat

    @model_validator(mode="after")
    def validate_order(self) -> Interval:
        """Reject empty and reversed intervals."""
        if self.end_sec <= self.start_sec:
            raise ValueError("end_sec must be greater than start_sec")
        return self


class SourceRecord(BaseModel):
    """Immutable metadata for an uploaded recording."""

    source_id: str
    meeting_id: str
    original_name: str
    original_artifact_id: str
    sha256: str
    sample_rate: int = Field(gt=0)
    channels: int = Field(gt=0)
    sample_count: int = Field(gt=0)
    device_label: str | None = None
    near_speaker_id: str | None = None


class TimeMappingRecord(BaseModel):
    """Serializable affine or piecewise source-to-meeting time mapping."""

    mapping_id: str
    source_id: str
    reference_id: str
    origin_shift_sec: float = 0
    kind: Literal["affine", "piecewise"]
    scale: PositiveFloat | None = None
    offset_sec: float | None = None
    knots: list[tuple[float, float]] = Field(default_factory=list)
    valid_ranges: list[Interval] = Field(default_factory=list)
    residual_seconds: list[float] = Field(default_factory=list)
    method: str
    status: Literal["aligned", "needs_review", "alignment_failed", "drift_unresolved"]


class SpeakerCandidate(BaseModel):
    """Named identity candidate and its cosine score, never a probability."""

    speaker_id: str
    cosine_score: float = Field(ge=-1, le=1)


class SelectedSpan(BaseModel):
    """Candidate/source used for one contiguous portion of an ASR clip."""

    source_id: str
    candidate_id: str
    interval: Interval


class SourceEvidence(BaseModel):
    """Explainable quality, identity and selection evidence for one candidate."""

    source_id: str
    candidate_id: str | None = None
    available: bool
    eligible: bool
    reason: str | None = None
    raw_quality_features: dict[str, float | None] = Field(default_factory=dict)
    identity_weight: float = Field(ge=0, le=1)
    selection_weight: float = Field(ge=0, le=1)
    candidate_scores: dict[str, float] = Field(default_factory=dict)


class OriginalSpan(BaseModel):
    """Trace one interval to decoded samples in an original source."""

    source_id: str
    start_sample: int = Field(ge=0)
    end_sample: int = Field(gt=0)
    start_sec: NonNegativeFloat
    end_sec: PositiveFloat
    mapping_id: str


class Provenance(BaseModel):
    """Transformation chain required to reproduce a timeline segment."""

    original_spans: list[OriginalSpan]
    speech_interval: Interval
    clip_interval: Interval
    transform_chain: list[str]
    separation_model_revision: str | None = None
    speaker_profile_version: int | None = None
    asr_model_revision: str | None = None


class TimelineSegment(BaseModel):
    """Version 1 timeline row; overlapping rows are represented independently."""

    segment_id: str
    track_id: str
    start_sec: NonNegativeFloat
    end_sec: PositiveFloat
    meeting_speaker_id: str | None = None
    speaker_id: str | None
    speaker_label: str | None = None
    speaker_status: SpeakerStatus
    speaker_match_score: float | None = Field(default=None, ge=-1, le=1)
    speaker_top_candidates: list[SpeakerCandidate] = Field(default_factory=list)
    speaker_evidence: dict[str, Any] = Field(default_factory=dict)
    overlap_group_id: str | None = None
    text: str
    asr_status: Literal["transcribed", "empty", "failed", "not_run"]
    needs_review: bool
    warnings: list[str] = Field(default_factory=list)
    selected_source_id: str | None = None
    selected_spans: list[SelectedSpan] = Field(default_factory=list)
    source_evidence: list[SourceEvidence] = Field(default_factory=list)
    original_clip_artifact_ids: list[str] = Field(default_factory=list)
    processed_clip_artifact_id: str | None = None
    asr_input_artifact_id: str | None = None
    alternative_clip_artifact_ids: list[str] = Field(default_factory=list)
    evidence_clip_artifact_id: str | None = None
    speech_region_id: str | None = None
    asr_chunk_ids: list[str] = Field(default_factory=list)
    provenance: Provenance

    @model_validator(mode="after")
    def validate_timeline_interval(self) -> TimelineSegment:
        """Apply the global half-open interval invariant."""
        if self.end_sec <= self.start_sec:
            raise ValueError("end_sec must be greater than start_sec")
        return self


class RunManifest(BaseModel):
    """Reproducibility metadata and stage artifact index for one run."""

    schema_version: str
    run_id: str
    input_hashes: dict[str, str]
    profile_versions: dict[str, int]
    model_revisions: dict[str, str]
    config_hash: str
    code_hash: str
    environment_lock_hash: str
    seed: int
    hardware: dict[str, str]
    created_at: datetime
    completed_at: datetime | None = None
    stage_artifacts: dict[str, list[str]] = Field(default_factory=dict)
    stage_durations_sec: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
