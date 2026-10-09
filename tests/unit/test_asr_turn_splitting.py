"""Long-turn ASR chunks retain identity and context without crossing speakers."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np

from meeting_pipeline.config import load_config
from meeting_pipeline.pipeline.stages.safe_merge import (
    MergedSpeakerTurn,
    asr_context_boundaries,
    split_merged_turns_for_asr,
)


def _turn(start: float, end: float) -> MergedSpeakerTurn:
    return MergedSpeakerTurn(
        turn_id="original",
        start_sec=start,
        end_sec=end,
        speaker_count=1,
        sub_turn_ids=["original-a", "original-b"],
        cluster_id="cluster-1",
        meeting_speaker_id="ms-1",
        speaker_label="Minh",
        speaker_status="identified",
        speech_region_id="region-1",
        track_id="local-1",
    )


def test_long_turn_splits_near_pause_retaining_identity_and_internal_context() -> None:
    config = load_config(Path("configs/default.yaml")).asr
    sr = 1000
    audio = np.ones(70000, dtype=np.float32)
    audio[20900:21100] = 0.001
    original = _turn(0.0, 60.0)
    chunks = split_merged_turns_for_asr([original], config, audio, sr)
    assert len(chunks) >= 3
    assert 20.9 <= chunks[0].end_sec <= 21.1
    assert chunks[0].start_sec == 0
    assert chunks[-1].end_sec == 60
    for index, chunk in enumerate(chunks):
        assert chunk.meeting_speaker_id == "ms-1"
        assert chunk.sub_turn_ids == original.sub_turn_ids
        assert chunk.asr_chunk_group_id == "original"
        assert chunk.duration_sec + 2 * config.chunk_context_seconds <= 25.0001
        if index:
            assert chunks[index - 1].end_sec == chunk.start_sec
        assert asr_context_boundaries(chunks, index) == (0.0, None)


def test_internal_context_still_capped_by_outer_speakers() -> None:
    config = load_config(Path("configs/default.yaml")).asr
    middle = split_merged_turns_for_asr(
        [_turn(2.0, 52.0)], config, np.ones(54000, dtype=np.float32), 1000
    )
    previous = replace(_turn(0, 2), turn_id="before", track_id="local-2")
    following = replace(_turn(52, 54), turn_id="after", track_id="local-3")
    turns = [previous, *middle, following]
    for index in range(1, len(turns) - 1):
        assert asr_context_boundaries(turns, index) == (2, 52)


def test_remainder_is_balanced_without_a_meaningless_short_tail() -> None:
    config = load_config(Path("configs/default.yaml")).asr
    chunks = split_merged_turns_for_asr(
        [_turn(2, 26)], config, np.ones(30000, dtype=np.float32), 1000
    )
    assert len(chunks) == 2
    assert all(chunk.duration_sec >= 9 for chunk in chunks)


def test_overlap_remains_unsplit() -> None:
    overlap = replace(_turn(0, 60), speaker_count=2, overlap_group_id="ov-1")
    config = load_config(Path("configs/default.yaml")).asr
    assert split_merged_turns_for_asr(
        [overlap], config, np.ones(60000, dtype=np.float32), 1000
    ) == [overlap]
