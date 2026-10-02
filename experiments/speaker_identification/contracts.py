"""Contracts and type definitions for speaker identification benchmark."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class SpeakerEncoder(Protocol):
    """Protocol for unified speaker encoders."""

    encoder_id: str
    model_id: str
    model_revision: str
    sample_rate: int
    embedding_dimension: int

    def encode(self, waveform: np.ndarray) -> np.ndarray:
        """Return one finite, one-dimensional, L2-normalized embedding."""
        ...


@dataclass(frozen=True)
class UtteranceSample:
    """Information representing one utterance."""

    utterance_id: str
    speaker_id: str
    audio_path: str | None = None
    shard: str | None = None
    row_index: int | None = None
    duration_sec: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UtteranceSample:
        return cls(
            utterance_id=str(data["utterance_id"]),
            speaker_id=str(data["speaker_id"]),
            audio_path=data.get("audio_path"),
            shard=data.get("shard"),
            row_index=data.get("row_index"),
            duration_sec=float(data["duration_sec"])
            if data.get("duration_sec") is not None
            else None,
        )


@dataclass
class EpisodeManifestRecord:
    """Single episode definition in an immutable manifest."""

    dataset: str
    split: str
    episode_id: int
    seed: int
    few_shot_k: int
    protocol: str  # 'closed_set' | 'open_set'
    known_speakers: list[str]
    unknown_speakers: list[str]
    support_utterances: dict[str, list[dict[str, Any]]]
    query_utterances: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EpisodeManifestRecord:
        return cls(
            dataset=str(data["dataset"]),
            split=str(data["split"]),
            episode_id=int(data["episode_id"]),
            seed=int(data["seed"]),
            few_shot_k=int(data["few_shot_k"]),
            protocol=str(data["protocol"]),
            known_speakers=list(data["known_speakers"]),
            unknown_speakers=list(data["unknown_speakers"]),
            support_utterances=dict(data["support_utterances"]),
            query_utterances=list(data["query_utterances"]),
        )


@dataclass(frozen=True)
class ClassifierPrediction:
    """Output prediction for one query embedding."""

    predicted_speaker_id: str  # speaker_id or 'unknown'
    predicted_unknown: bool
    top1_score: float
    top2_score: float
    margin: float
    top_candidates: list[tuple[str, float]] = field(default_factory=list)


@dataclass
class RawPredictionRecord:
    """24 mandatory fields for predictions.csv per Section 9.4."""

    run_id: str
    dataset: str
    split: str
    protocol: str
    episode_id: int
    few_shot_k: int
    encoder_id: str
    classifier_id: str
    query_id: str
    true_speaker_id: str
    is_known: bool
    predicted_speaker_id: str
    predicted_unknown: bool
    top1_score: float
    top2_score: float
    margin: float
    score_threshold: float
    margin_threshold: float
    correct: bool
    audio_duration_sec: float
    feature_latency_ms: float
    classifier_latency_ms: float
    end_to_end_latency_ms: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
