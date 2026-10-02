"""Domain models for VAD, chunking, transcription, and speech regions."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from meeting_pipeline.domain.schemas import Interval


class SpeechRegion(BaseModel):
    """Contiguous meeting-time interval where speech is detected across valid sources."""

    region_id: str
    start_sec: float
    end_sec: float
    supporting_source_ids: list[str]
    source_intervals: dict[str, Interval]
    confidence: float | None = None
    speaker_count: int | None = None
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_region(self) -> SpeechRegion:
        if self.end_sec <= self.start_sec:
            raise ValueError("end_sec must be strictly greater than start_sec")
        return self


class AsrChunk(BaseModel):
    """Segment of audio prepared for ASR with an assigned core ownership interval."""

    chunk_id: str
    region_id: str
    source_id: str
    core_interval: Interval
    clip_interval: Interval
    clip_artifact_id: str

    @model_validator(mode="after")
    def validate_intervals(self) -> AsrChunk:
        if (
            self.core_interval.start_sec < self.clip_interval.start_sec - 1e-5
            or self.core_interval.end_sec > self.clip_interval.end_sec + 1e-5
        ):
            raise ValueError("core_interval must be contained within clip_interval")
        return self


class TimedWord(BaseModel):
    """Individual recognized word or token unit with meeting-level timestamps."""

    text: str
    start_sec: float
    end_sec: float
    confidence: float | None = None

    @model_validator(mode="after")
    def validate_word(self) -> TimedWord:
        if not self.text.strip():
            raise ValueError("text must not be empty after stripping whitespace")
        if self.end_sec < self.start_sec:
            raise ValueError("end_sec must be >= start_sec")
        return self


class ChunkTranscript(BaseModel):
    """Raw output of an ASR model on a single chunk."""

    chunk_id: str
    raw_text: str
    words: list[TimedWord]
    status: Literal["transcribed", "empty", "failed", "unreliable"]
    warnings: list[str] = Field(default_factory=list)
