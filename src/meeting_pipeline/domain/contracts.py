"""Pydantic data contracts for VIVOS synthetic pipeline.

Specification: Section 5 of docs/PLAN_VIVOS_SYNTHETIC_PIPELINE.md.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator

NonNegativeFloat = Annotated[float, Field(ge=0)]
PositiveFloat = Annotated[float, Field(gt=0)]


class UtteranceRecord(BaseModel):
    """Manifest record representing a single VIVOS audio file."""

    schema_version: str = "1.0"
    utterance_id: str
    audio_path: str
    audio_sha256: str
    speaker_id: str
    text_raw: str
    text_normalized: str
    duration_sec: PositiveFloat
    sample_rate: int = 16000
    split: Literal["development", "validation", "test"]
    is_enrollment: bool = False


class TurnRecord(BaseModel):
    """Canonical meeting turn representing a speech utterance placed in time."""

    turn_id: str
    speaker_id: str
    utterance_id: str
    start_sec: NonNegativeFloat
    end_sec: PositiveFloat
    text_raw: str
    text_normalized: str

    @model_validator(mode="after")
    def validate_interval(self) -> TurnRecord:
        if self.end_sec <= self.start_sec:
            raise ValueError(f"end_sec ({self.end_sec}) must be > start_sec ({self.start_sec})")
        return self


class RoomConfig(BaseModel):
    """3D acoustic room geometry and reverberation parameters."""

    dimensions: list[float] = Field(min_length=3, max_length=3)
    rt60: PositiveFloat


class DeviceConfig(BaseModel):
    """Parameters for a recording device placed in the meeting room."""

    device_id: str
    position: list[float] = Field(min_length=3, max_length=3)
    gain_db: float = 0.0
    snr_db: float = 20.0
    noise_type: str = "white"
    drift_ppm: float = 0.0
    offset_sec: float = 0.0
    clipping_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    dropout_count: int = Field(default=0, ge=0)


class MeetingRecipe(BaseModel):
    """Canonical meeting recipe defining exact placement, timing and devices."""

    schema_version: str = "1.0"
    meeting_id: str
    split: Literal["development", "validation", "test"]
    seed: int
    profile: str
    speakers: list[str]
    speaker_positions: dict[str, list[float]]
    enrollment_utterances: dict[str, list[str]]
    turns: list[TurnRecord]
    room: RoomConfig
    devices: dict[str, DeviceConfig]
    canonical_duration_sec: PositiveFloat
    manifest_hash: str
    config_hash: str
    code_hash: str | None = None


class MeetingSegment(BaseModel):
    """Temporal segment predicted by multi-source VAD."""

    schema_version: str = "1.0"
    meeting_id: str
    segment_id: str
    start_sec: NonNegativeFloat
    end_sec: PositiveFloat
    overlap: bool = False
    reference_speaker_id: str | None = None
    reference_text: str | None = None

    @model_validator(mode="after")
    def validate_interval(self) -> MeetingSegment:
        if self.end_sec <= self.start_sec:
            raise ValueError(f"end_sec ({self.end_sec}) must be > start_sec ({self.start_sec})")
        return self


class WordHypothesis(BaseModel):
    """Word-level hypothesis with timestamp and confidence."""

    word: str
    start_sec: NonNegativeFloat
    end_sec: PositiveFloat
    asr_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    time_status: Literal["exact", "uncertain"] = "exact"


class SourceHypothesis(BaseModel):
    """ASR hypothesis and acoustic quality features for one (segment, source)."""

    meeting_id: str
    segment_id: str
    source_id: str
    text: str
    words: list[WordHypothesis] = Field(default_factory=list)
    audio_features: dict[str, float] = Field(default_factory=dict)
    asr_features: dict[str, float | None] = Field(default_factory=dict)
    asr_status: Literal[
        "transcribed", "empty", "failed", "unreliable", "not_run", "abstained"
    ] = "transcribed"
    asr_warnings: list[str] = Field(default_factory=list)
    raw_asr_candidates: list[dict[str, Any]] = Field(default_factory=list)
    audio_quality_score: float = Field(default=0.0, ge=0.0, le=1.0)
    transcript_quality_score: float = Field(default=0.0, ge=0.0, le=1.0)
    routing_reason: str | None = None


class WordProvenance(BaseModel):
    """Traceability for a fused token."""

    output_word: str
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    supporting_sources: list[str]
    source_scores: dict[str, float] = Field(default_factory=dict)
    representative_source_id: str


class FinalTimelineItem(BaseModel):
    """Final output timeline segment after multi-source fusion."""

    schema_version: str = "1.0"
    meeting_id: str
    segment_id: str
    start_sec: NonNegativeFloat
    end_sec: PositiveFloat
    speaker_id: str
    speaker_confidence: float = Field(ge=0.0, le=1.0)
    text: str
    transcript_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    primary_source_id: str
    source_scores: dict[str, float] = Field(default_factory=dict)
    word_provenance: list[WordProvenance] = Field(default_factory=list)
    evidence_clips: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_interval(self) -> FinalTimelineItem:
        if self.end_sec <= self.start_sec:
            raise ValueError(f"end_sec ({self.end_sec}) must be > start_sec ({self.start_sec})")
        return self


# ---------------------------------------------------------------------------
# Config Models for Schema Validation of YAML Configs
# ---------------------------------------------------------------------------


class VivosDataConfig(BaseModel):
    """Validation schema for configs/data/vivos.yaml."""

    vivos_root: str
    manifest_output_path: str
    splits_output_path: str
    catalog_output_path: str
    development_speaker_count: int = Field(gt=0)
    validation_speaker_count: int = Field(gt=0)
    test_speaker_count: int = Field(gt=0)
    min_enrollment_utterances: int = Field(default=5, gt=0)
    min_enrollment_duration_sec: float = Field(default=30.0, gt=0)
    target_sample_rate: int = 16000
    target_channels: int = 1
    seed: int = 42


class SimulationProfileConfig(BaseModel):
    """Validation schema for configs/simulation/*.yaml."""

    profile_name: str
    description: str
    room_dimensions: list[float] = Field(min_length=3, max_length=3)
    rt60_range: list[float] = Field(min_length=2, max_length=2)
    num_speakers: int = Field(ge=2)
    num_devices: int = Field(ge=2)
    turn_pause_range: list[float] = Field(min_length=2, max_length=2)
    min_meeting_duration_sec: PositiveFloat
    max_meeting_duration_sec: PositiveFloat
    snr_db_range: list[float] = Field(min_length=2, max_length=2)
    noise_types: list[str]
    allow_vivos_babble: bool = False
    offset_sec_range: list[float] = Field(min_length=2, max_length=2)
    drift_ppm_range: list[float] = Field(min_length=2, max_length=2)
    clipping_ratio_range: list[float] = Field(min_length=2, max_length=2)
    dropout_count_range: list[int] = Field(min_length=2, max_length=2)


class AsrModelConfig(BaseModel):
    model_id: str
    revision: str
    cache_dir: str
    language: str = "vi"
    task: str = "transcribe"
    return_timestamps: bool = True


class SpeakerEncoderConfig(BaseModel):
    model_id: str
    revision: str
    cache_dir: str
    embedding_dim: int = 192


class VadConfig(BaseModel):
    backend: str = "silero"
    threshold: float = 0.5
    min_speech_sec: float = 0.25
    min_silence_sec: float = 0.30
    merge_gap_sec: float = 0.25
    padding_sec: float = 0.15
    max_segment_sec: float = 15.0


class ModelsConfig(BaseModel):
    """Validation schema for configs/models/default.yaml."""

    asr: AsrModelConfig
    speaker_encoder: SpeakerEncoderConfig
    vad: VadConfig


class FusionConfig(BaseModel):
    """Validation schema for configs/fusion/default.yaml."""

    baselines: list[str]
    audio_quality: dict[str, Any]
    transcript_quality: dict[str, Any]
    alignment: dict[str, Any]
    learned_fusion: dict[str, Any]


class ExperimentConfig(BaseModel):
    """Validation schema for configs/experiment/*.yaml."""

    model_config = {"populate_by_name": True}

    experiment_name: str
    seed: int = 42
    data_config: str
    simulation_profile: str | None = None
    simulation_profiles: list[str] | None = None
    models_config: str = Field(alias="model_config")
    fusion_config: str
    meetings_per_split: dict[str, int] | None = None
    target_minutes_per_split: dict[str, float] | None = None
    enrollment_durations_sec: list[float] = Field(default_factory=lambda: [5.0, 15.0, 30.0])
    output_dirs: dict[str, str]
