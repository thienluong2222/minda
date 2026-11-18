"""Validated YAML configuration with no secret serialization."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


class PathsConfig(BaseModel):
    data_dir: Path
    database_path: Path
    model_cache_dir: Path


class AudioConfig(BaseModel):
    analysis_sample_rate: int = Field(16000, gt=0)
    separator_sample_rate: int = Field(8000, gt=0)
    max_sources: int = Field(8, ge=1, le=8)
    max_profiles: int = Field(8, ge=1, le=8)
    max_duration_seconds: float = Field(7200, gt=0)
    max_upload_bytes: int = Field(gt=0)
    preserve_originals: bool = True


class SyncConfig(BaseModel):
    envelope_rate_hz: int = Field(100, gt=0)
    max_offset_seconds: float = Field(120, gt=0)
    fine_window_seconds: float = Field(8, gt=0)
    long_recording_step_seconds: float = Field(30, gt=0)
    minimum_common_speech_seconds: float = Field(3, gt=0)
    allow_drift: bool = True
    minimum_drift_inliers: int = Field(3, ge=3)


class SegmentationConfig(BaseModel):
    vad_threshold: float = Field(0.5, ge=0.0, le=1.0)
    minimum_speech_ms: int = Field(250, ge=0)
    minimum_silence_ms: int = Field(200, ge=0)
    merge_gap_ms: int = Field(400, ge=0)
    speech_pad_ms: int = Field(250, ge=0)
    turn_gap_bridge_ms: int = Field(400, ge=0)
    context_seconds: float = Field(10.0, gt=0)
    step_seconds: float = Field(2.5, gt=0)
    max_local_speakers: int = Field(3, ge=1)
    max_simultaneous_speakers: int = Field(2, ge=1)

    def __getitem__(self, item: str) -> object:
        return getattr(self, item)


class AsrModelReference(BaseModel):
    """Immutable identity of one Hugging Face checkpoint."""

    model_id: str
    model_revision: str


class AsrConfig(BaseModel):
    model_id: str
    model_revision: str
    model_variants: dict[str, AsrModelReference] = Field(default_factory=dict)
    language: str = "vi"
    runtime: Literal["cpu", "mps", "auto", "mlx"] = "cpu"
    auto_backend: Literal["mps", "mlx"] = "mps"
    mlx_runtime_python: str = ".venv-asr-mlx/bin/python"
    mlx_model_dir: str = ""
    target_core_seconds: float = Field(default=22.0, gt=0)
    max_chunk_seconds: float = Field(default=25.0, gt=0)
    chunk_context_seconds: float = Field(default=0.75, ge=0)
    boundary_search_seconds: float = Field(default=2.0, ge=0)
    sentence_pause_seconds: float = Field(default=0.8, gt=0)
    max_sentence_seconds: float = Field(default=15.0, gt=0)
    evidence_pad_seconds: float = Field(default=0.2, ge=0)
    max_new_tokens_per_second: float = Field(default=10.0, gt=0)
    min_new_tokens: int = Field(default=32, ge=8)
    max_new_tokens: int = Field(default=224, ge=32)
    max_decode_attempts: int = Field(default=2, ge=1, le=3)
    max_words_per_second: float = Field(default=8.0, gt=0)
    max_consecutive_token_repeats: int = Field(default=5, ge=2)
    max_consecutive_ngram_repeats: int = Field(default=4, ge=2)
    max_consecutive_punctuation: int = Field(default=6, ge=3)
    min_compression_ratio: float = Field(default=0.12, gt=0, le=1)
    timestamp_tolerance_seconds: float = Field(default=0.1, ge=0)
    routing_mode: Literal["adaptive", "all_source"] = "adaptive"
    adaptive_delta_threshold: float = Field(default=0.05, ge=0.0, le=1.0)
    safe_turn_merging: bool = Field(default=True)
    max_merge_gap_seconds: float = Field(default=0.6, ge=0.0)
    cache_enabled: bool = Field(default=True)

    def __getitem__(self, item: str) -> object:
        return getattr(self, item)

    def for_variant(self, name: str) -> AsrConfig:
        """Select a pinned checkpoint for controlled small/medium comparisons."""
        if name not in self.model_variants:
            raise ValueError(f"Unknown ASR model variant: {name}")
        reference = self.model_variants[name]
        return self.model_copy(
            update={"model_id": reference.model_id, "model_revision": reference.model_revision}
        )

    @model_validator(mode="after")
    def validate_invariants(self) -> AsrConfig:
        if self.target_core_seconds >= self.max_chunk_seconds:
            raise ValueError("target_core_seconds must be less than max_chunk_seconds")
        if self.target_core_seconds + 2 * self.chunk_context_seconds > self.max_chunk_seconds:
            raise ValueError(
                "target_core_seconds + 2 * chunk_context_seconds must be <= max_chunk_seconds"
            )
        if self.boundary_search_seconds >= self.target_core_seconds / 2:
            raise ValueError("boundary_search_seconds must be < target_core_seconds / 2")
        return self


class DatasetConfig(BaseModel):
    total_download_budget_bytes: int = Field(gt=0)
    vivos_download_budget_bytes: int = Field(gt=0)
    libriwasn_download_budget_bytes: int = Field(gt=0)
    voxvietnam_download_budget_bytes: int = Field(gt=0)


def load_dataset_config(path: Path) -> DatasetConfig:
    """Load the dataset budget block from either full or evaluation-only YAML."""
    with path.open("r", encoding="utf-8") as stream:
        payload = yaml.safe_load(stream)
    return DatasetConfig.model_validate(payload["datasets"])


class PipelineConfig(BaseModel):
    """Top-level validated config. Extra stage blocks remain explicit dictionaries."""

    schema_version: str
    mode: Literal["development", "validated"]
    paths: PathsConfig
    audio: AudioConfig
    sync: SyncConfig
    segmentation: SegmentationConfig
    separation: dict[str, object]
    identity: dict[str, object]
    asr: AsrConfig
    models: dict[str, object]
    datasets: DatasetConfig
    worker: dict[str, object]


def load_config(path: Path) -> PipelineConfig:
    """Load and validate config without expanding environment secrets into snapshots."""
    with path.open("r", encoding="utf-8") as stream:
        payload = yaml.safe_load(stream)
    return PipelineConfig.model_validate(payload)
