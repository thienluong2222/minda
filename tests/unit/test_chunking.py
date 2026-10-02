"""Unit tests for chunk planning and invariant enforcement."""

from __future__ import annotations

import numpy as np
import pytest

from meeting_pipeline.config import AsrConfig
from meeting_pipeline.domain.schemas import Interval
from meeting_pipeline.domain.transcription import SpeechRegion
from meeting_pipeline.pipeline.stages.chunking import ChunkPlanner, plan_region_chunks


def _make_asr_config(**kwargs) -> AsrConfig:
    defaults = {
        "model_id": "vinai/PhoWhisper-small",
        "model_revision": "a86b604c346caf7148c37512eafe783a16420adb",
        "language": "vi",
        "target_core_seconds": 22.0,
        "max_chunk_seconds": 25.0,
        "chunk_context_seconds": 0.75,
        "boundary_search_seconds": 2.0,
        "sentence_pause_seconds": 0.8,
        "max_sentence_seconds": 15.0,
        "evidence_pad_seconds": 0.2,
    }
    defaults.update(kwargs)
    return AsrConfig(**defaults)


def _make_region(start: float, end: float, region_id: str = "reg-1") -> SpeechRegion:
    return SpeechRegion(
        region_id=region_id,
        start_sec=start,
        end_sec=end,
        supporting_source_ids=["src-1"],
        source_intervals={"src-1": Interval(start_sec=start, end_sec=end)},
        confidence=None,
        speaker_count=1,
    )


def test_short_region_single_chunk() -> None:
    """A region <= max_chunk_seconds produces exactly one chunk."""
    config = _make_asr_config()
    region = _make_region(5.0, 15.0)  # 10s duration

    chunks = plan_region_chunks(
        region=region,
        asr_config=config,
        meeting_duration=30.0,
    )

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.core_interval.start_sec == 5.0
    assert chunk.core_interval.end_sec == 15.0
    assert chunk.clip_interval.start_sec == 5.0 - 0.75
    assert chunk.clip_interval.end_sec == 15.0 + 0.75


def test_long_region_70s_multiple_chunks() -> None:
    """A 70s region is split into multiple chunks, each clip <= 25s."""
    config = _make_asr_config()
    region = _make_region(0.0, 70.0)

    planner = ChunkPlanner(config=config)
    chunks = planner.plan([region], meeting_duration=100.0)

    assert len(chunks) >= 3
    # Check that each clip is <= max_chunk_seconds
    for chunk in chunks:
        clip_dur = chunk.clip_interval.end_sec - chunk.clip_interval.start_sec
        assert clip_dur <= 25.0 + 1e-4

    # Check core coverage
    assert chunks[0].core_interval.start_sec == 0.0
    assert chunks[-1].core_interval.end_sec == 70.0

    # Check contiguous disjoint cores
    for i in range(len(chunks) - 1):
        assert abs(chunks[i].core_interval.end_sec - chunks[i + 1].core_interval.start_sec) < 1e-4


def test_context_clamping_at_boundaries() -> None:
    """Context is clamped at meeting origin (0.0) and meeting duration."""
    config = _make_asr_config(chunk_context_seconds=1.0)
    region = _make_region(0.2, 5.0)

    chunks = plan_region_chunks(
        region=region,
        asr_config=config,
        meeting_duration=5.1,
    )

    assert len(chunks) == 1
    # 0.2 - 1.0 clamped to 0.0
    assert chunks[0].clip_interval.start_sec == 0.0
    # 5.0 + 1.0 clamped to meeting_duration (5.1)
    assert chunks[0].clip_interval.end_sec == 5.1


def test_optimal_boundary_prefers_minimum_energy() -> None:
    """Chunk split point finds the minimum energy frame in search window."""
    config = _make_asr_config(
        target_core_seconds=20.0,
        max_chunk_seconds=25.0,
        boundary_search_seconds=2.0,
    )
    sr = 16000
    total_sec = 60.0
    # Create audio with silence/dip at exactly 21.0s
    audio = np.ones(int(total_sec * sr), dtype=np.float32)
    dip_start = int(20.9 * sr)
    dip_end = int(21.1 * sr)
    audio[dip_start:dip_end] = 0.001  # very quiet dip

    region = _make_region(0.0, 50.0)
    chunks = plan_region_chunks(
        region=region,
        asr_config=config,
        meeting_duration=total_sec,
        audio_samples=audio,
        sample_rate=sr,
    )

    assert len(chunks) >= 2
    # The first split should be placed around 21.0s where the dip was
    split_time = chunks[0].core_interval.end_sec
    assert abs(split_time - 21.0) < 0.2


def test_conflicting_config_rejected() -> None:
    """Pydantic rejects invalid or conflicting AsrConfig invariants."""
    # target_core >= max_chunk
    with pytest.raises(ValueError, match="target_core_seconds must be less than max_chunk_seconds"):
        _make_asr_config(target_core_seconds=25.0, max_chunk_seconds=25.0)

    # target_core + 2*context > max_chunk
    with pytest.raises(ValueError, match="must be <= max_chunk_seconds"):
        _make_asr_config(
            target_core_seconds=24.0,
            chunk_context_seconds=1.0,
            max_chunk_seconds=25.0,
        )

    with pytest.raises(
        ValueError, match="boundary_search_seconds must be < target_core_seconds / 2"
    ):
        _make_asr_config(
            target_core_seconds=10.0,
            boundary_search_seconds=6.0,
            max_chunk_seconds=25.0,
        )
