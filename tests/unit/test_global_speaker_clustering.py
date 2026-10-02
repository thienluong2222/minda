"""Unit tests for WP2: Global speaker clustering and open-set identification."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from meeting_pipeline.application.speakers import (
    SpeakerProfileInput,
    SpeakerRegistry,
    evaluate_sample_quality,
)
from meeting_pipeline.config import load_config
from meeting_pipeline.pipeline.speaker_turns import SpeakerTurn
from meeting_pipeline.speaker.clustering import GlobalSpeakerClusterer


class DummyEncoder:
    """Mock speaker encoder producing controlled embeddings based on waveform frequency/tag."""

    def __init__(self, dimension: int = 192) -> None:
        self.embedding_dimension = dimension
        self.model_id = "mock-encoder"
        self.revision = "v1"

    def encode(
        self, waveform: np.ndarray[Any, np.dtype[np.float32]]
    ) -> np.ndarray[Any, np.dtype[np.float32]]:
        mean_val = float(np.mean(waveform))
        vec = np.zeros(self.embedding_dimension, dtype=np.float32)
        if abs(mean_val - 0.2) < 0.1:
            vec[0] = 1.0
        elif abs(mean_val - 0.5) < 0.1:
            vec[1] = 1.0
        elif abs(mean_val - 0.7) < 0.1:
            vec[2] = 1.0
        else:
            np.random.seed(len(waveform) % 1000)
            vec = np.random.randn(self.embedding_dimension).astype(np.float32)
        norm = float(np.linalg.norm(vec))
        if norm > 1e-8:
            vec /= norm
        return vec


def _make_turn(
    turn_id: str,
    start_sec: float,
    end_sec: float,
    speaker_count: int = 1,
    track_id: str = "track-0",
    speech_region_id: str = "reg-0",
) -> SpeakerTurn:
    return SpeakerTurn(
        turn_id=turn_id,
        start_sec=start_sec,
        end_sec=end_sec,
        speech_region_id=speech_region_id,
        track_id=track_id,
        speaker_count=speaker_count,
    )


def test_clustering_zero_enrolled_profiles() -> None:
    """0 enrolled profiles: A-B-A-B -> 2 anonymous clusters, stable Người lạ 1, 2."""
    sr = 16000
    encoder = DummyEncoder(dimension=192)
    clusterer = GlobalSpeakerClusterer(
        encoder=encoder,
        cluster_threshold=0.40,
        assign_threshold=0.35,
        assign_margin=0.05,
        min_seed_duration_sec=0.5,
    )

    total_len = int(8.0 * sr)
    sig = np.zeros(total_len, dtype=np.float32)
    sig[int(0.0 * sr) : int(1.5 * sr)] = 0.2
    sig[int(2.0 * sr) : int(3.5 * sr)] = 0.5
    sig[int(4.0 * sr) : int(5.5 * sr)] = 0.2
    sig[int(6.0 * sr) : int(7.5 * sr)] = 0.5

    aligned = {"mic-1": sig}
    turns = [
        _make_turn("t1", 0.0, 1.5, track_id="track-A"),
        _make_turn("t2", 2.0, 3.5, track_id="track-B"),
        _make_turn("t3", 4.0, 5.5, track_id="track-A"),
        _make_turn("t4", 6.0, 7.5, track_id="track-B"),
    ]

    assignments, _cluster_decisions, summary = clusterer.cluster_and_identify(
        turns=turns,
        aligned_signals=aligned,
        sample_rate=sr,
        profiles=[],
    )

    assert summary["total_clusters"] == 2
    assert summary["unknown_count"] == 2
    assert summary["identified_count"] == 0

    assert assignments["t1"].speaker_label == "Người lạ 1"
    assert assignments["t2"].speaker_label == "Người lạ 2"
    assert assignments["t3"].speaker_label == "Người lạ 1"
    assert assignments["t4"].speaker_label == "Người lạ 2"

    assert assignments["t1"].meeting_speaker_id == "ms-0001"
    assert assignments["t2"].meeting_speaker_id == "ms-0002"
    assert assignments["t3"].meeting_speaker_id == "ms-0001"
    assert assignments["t4"].meeting_speaker_id == "ms-0002"


def test_clustering_partial_enrollment() -> None:
    """Partial enrollment: 1 enrolled matches Speaker A; Speaker B becomes Người lạ 1."""
    sr = 16000
    encoder = DummyEncoder(dimension=192)
    clusterer = GlobalSpeakerClusterer(
        encoder=encoder,
        cluster_threshold=0.40,
        assign_threshold=0.35,
        assign_margin=0.05,
        enrolled_match_threshold=0.45,
        enrolled_margin=0.08,
        min_seed_duration_sec=0.5,
    )

    sig = np.zeros(int(4.0 * sr), dtype=np.float32)
    sig[int(0.0 * sr) : int(1.5 * sr)] = 0.2  # Speaker A
    sig[int(2.0 * sr) : int(3.5 * sr)] = 0.5  # Speaker B

    aligned = {"mic-1": sig}
    turns = [
        _make_turn("t1", 0.0, 1.5),
        _make_turn("t2", 2.0, 3.5),
    ]

    enrolled_a_vec = np.zeros(192, dtype=np.float32)
    enrolled_a_vec[0] = 1.0  # Exact match for Speaker A
    profile_a = SpeakerProfileInput(
        speaker_id="spk-alice",
        display_name="Alice Nguyen",
        embedding=enrolled_a_vec,
    )

    assignments, _cluster_decisions, summary = clusterer.cluster_and_identify(
        turns=turns,
        aligned_signals=aligned,
        sample_rate=sr,
        profiles=[profile_a],
    )

    assert summary["identified_count"] == 1
    assert summary["unknown_count"] == 1

    assert assignments["t1"].speaker_status == "identified"
    assert assignments["t1"].speaker_label == "Alice Nguyen"
    assert assignments["t1"].speaker_id == "spk-alice"

    assert assignments["t2"].speaker_status == "unknown"
    assert assignments["t2"].speaker_label == "Người lạ 1"
    assert assignments["t2"].speaker_id is None


def test_clustering_overlap_and_ambiguous_short_turns() -> None:
    """Overlap turns are skipped; ambiguous short turns are marked Chưa xác định."""
    sr = 16000
    encoder = DummyEncoder(dimension=192)
    clusterer = GlobalSpeakerClusterer(
        encoder=encoder,
        cluster_threshold=0.40,
        assign_threshold=0.80,  # High threshold to trigger ambiguity
        assign_margin=0.20,
        min_seed_duration_sec=1.0,
    )

    sig = np.zeros(int(4.0 * sr), dtype=np.float32)
    sig[int(0.0 * sr) : int(1.5 * sr)] = 0.2  # Seed turn
    sig[int(2.0 * sr) : int(2.4 * sr)] = 0.7  # Short unassigned turn

    aligned = {"mic-1": sig}
    turns = [
        _make_turn("t1", 0.0, 1.5, speaker_count=1),
        _make_turn("t2_overlap", 1.5, 2.0, speaker_count=2),
        _make_turn("t3_short", 2.0, 2.4, speaker_count=1),
    ]

    assignments, _cluster_decisions, _summary = clusterer.cluster_and_identify(
        turns=turns,
        aligned_signals=aligned,
        sample_rate=sr,
        profiles=[],
    )

    # Overlap turn check
    overlap_assign = assignments["t2_overlap"]
    assert overlap_assign.speaker_label == "Nói chồng"
    assert overlap_assign.speaker_status == "ambiguous"
    assert overlap_assign.needs_review is True
    assert overlap_assign.meeting_speaker_id is None

    # Ambiguous short turn check
    short_assign = assignments["t3_short"]
    assert short_assign.speaker_label == "Chưa xác định"
    assert short_assign.speaker_status == "ambiguous"
    assert short_assign.needs_review is True
    assert short_assign.meeting_speaker_id is None


def test_voice_quality_screening() -> None:
    """evaluate_sample_quality rejects silence, short speech, and extreme clipping."""
    sr = 16000
    # 1. Pure silence
    silent = np.zeros(sr * 2, dtype=np.float32)
    qual = evaluate_sample_quality(silent, sr)
    assert not qual["valid"]
    assert "insufficient_speech" in str(qual["reason"])

    # 2. Too short active speech (< 0.5s)
    short = np.zeros(sr * 2, dtype=np.float32)
    short[: int(0.3 * sr)] = 0.5
    qual_short = evaluate_sample_quality(short, sr)
    assert not qual_short["valid"]

    # 3. Excessive clipping
    clipped = np.ones(sr * 2, dtype=np.float32)
    qual_clip = evaluate_sample_quality(clipped, sr)
    assert qual_clip["clipping_ratio"] > 0.9

    # 4. Valid speech (with natural pauses so noise floor contrast is valid)
    good = np.zeros(sr * 4, dtype=np.float32)
    t = np.arange(int(sr * 2.5), dtype=np.float32) / sr
    good[int(sr * 0.5) : int(sr * 0.5) + len(t)] = (0.3 * np.sin(2 * np.pi * 300 * t)).astype(
        np.float32
    )
    qual_good = evaluate_sample_quality(good, sr)
    assert qual_good["valid"]
    assert qual_good["speech_sec"] >= 2.0


def test_profile_registry_dimension_reencoding(tmp_path: Path) -> None:
    """Registry automatically re-encodes when current encoder dimension mismatches profile."""
    config = load_config(Path("configs/default.yaml"))
    config.paths.data_dir = tmp_path / "data"

    sr = 16000
    audio = np.zeros(sr * 4, dtype=np.float32)
    t = np.arange(int(sr * 2.5), dtype=np.float32) / sr
    audio[int(sr * 0.5) : int(sr * 0.5) + len(t)] = (0.3 * np.sin(2 * np.pi * 200 * t)).astype(
        np.float32
    )
    sample_file = tmp_path / "sample1.wav"
    sf.write(sample_file, audio, sr)

    enc1 = DummyEncoder(dimension=192)
    registry1 = SpeakerRegistry(config)
    registry1._encoder = enc1

    profile = registry1.enroll("Test User", [sample_file])
    spk_id = str(profile["speaker_id"])
    assert profile["embedding_dimension"] == 192

    loaded1 = registry1.load([spk_id])
    assert len(loaded1) == 1
    assert loaded1[0].embedding.shape[0] == 192

    # Switch to 256-dim encoder
    enc2 = DummyEncoder(dimension=256)
    registry2 = SpeakerRegistry(config)
    registry2._encoder = enc2

    loaded2 = registry2.load([spk_id])
    assert len(loaded2) == 1
    assert loaded2[0].embedding.shape[0] == 256
