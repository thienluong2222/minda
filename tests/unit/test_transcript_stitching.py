"""Unit tests for transcript stitching and core ownership."""

from __future__ import annotations

from meeting_pipeline.domain.schemas import Interval
from meeting_pipeline.domain.transcription import AsrChunk, ChunkTranscript, TimedWord
from meeting_pipeline.pipeline.stages.transcript_stitching import stitch_chunks


def _make_chunk(
    chunk_id: str,
    core_start: float,
    core_end: float,
    clip_start: float,
    clip_end: float,
) -> AsrChunk:
    return AsrChunk(
        chunk_id=chunk_id,
        region_id="reg-1",
        source_id="src-1",
        core_interval=Interval(start_sec=core_start, end_sec=core_end),
        clip_interval=Interval(start_sec=clip_start, end_sec=clip_end),
        clip_artifact_id=f"clips/asr-input/{chunk_id}.wav",
    )


def test_core_ownership_filters_outside_tokens() -> None:
    """Tokens whose midpoint falls outside the chunk's core interval are discarded."""
    # Chunk 1: core [0.0, 10.0), clip [0.0, 11.0)
    # Chunk 2: core [10.0, 20.0), clip [9.0, 20.0)
    chunk1 = _make_chunk("c1", 0.0, 10.0, 0.0, 11.0)
    chunk2 = _make_chunk("c2", 10.0, 20.0, 9.0, 20.0)

    # Word at 10.5 in chunk 1 has midpoint 10.5 >= 10.0 -> must be filtered from chunk 1
    t1 = ChunkTranscript(
        chunk_id="c1",
        raw_text="xin chào các bạn",
        words=[
            TimedWord(text="xin", start_sec=1.0, end_sec=2.0),  # midpoint 1.5 in c1 core
            TimedWord(text="chào", start_sec=2.0, end_sec=3.0),  # midpoint 2.5 in c1 core
            TimedWord(text="các", start_sec=9.0, end_sec=10.0),  # midpoint 9.5 in c1 core
            TimedWord(text="bạn", start_sec=10.2, end_sec=10.8),  # midpoint 10.5 OUTSIDE c1 core
        ],
        status="transcribed",
    )
    # Word at 10.2 in chunk 2 (within chunk 2 core)
    t2 = ChunkTranscript(
        chunk_id="c2",
        raw_text="bạn hôm nay",
        words=[
            TimedWord(text="các", start_sec=9.0, end_sec=9.8),  # midpoint 9.4 OUTSIDE c2 core
            TimedWord(text="bạn", start_sec=10.2, end_sec=10.8),  # midpoint 10.5 in c2 core
            TimedWord(text="hôm", start_sec=11.0, end_sec=12.0),  # midpoint 11.5 in c2 core
            TimedWord(text="nay", start_sec=12.0, end_sec=13.0),  # midpoint 12.5 in c2 core
        ],
        status="transcribed",
    )

    stitched = stitch_chunks([t1, t2], [chunk1, chunk2])

    assert [w.text for w in stitched.words] == ["xin", "chào", "các", "bạn", "hôm", "nay"]
    assert stitched.full_text == "xin chào các bạn hôm nay"


def test_boundary_duplicate_deduplication() -> None:
    """Identical tokens at the boundary within tolerance are deduplicated."""
    chunk1 = _make_chunk("c1", 0.0, 10.0, 0.0, 10.5)
    chunk2 = _make_chunk("c2", 10.0, 20.0, 9.5, 20.0)

    # Both chunks barely include "thì" at the 10.0s boundary
    t1 = ChunkTranscript(
        chunk_id="c1",
        raw_text="nói thì",
        words=[
            TimedWord(text="nói", start_sec=8.0, end_sec=9.0),
            TimedWord(text="thì", start_sec=9.7, end_sec=10.0),  # midpoint 9.85 < 10.0
        ],
        status="transcribed",
    )
    t2 = ChunkTranscript(
        chunk_id="c2",
        raw_text="thì được",
        words=[
            TimedWord(text="thì", start_sec=10.0, end_sec=10.3),  # midpoint 10.15 >= 10.0
            TimedWord(text="được", start_sec=10.5, end_sec=11.5),
        ],
        status="transcribed",
    )

    stitched = stitch_chunks([t1, t2], [chunk1, chunk2])

    # "thì" should only appear once
    assert [w.text for w in stitched.words] == ["nói", "thì", "được"]
    assert stitched.discarded_overlap_count == 1


def test_identical_words_at_different_times_preserved() -> None:
    """Identical words occurring at different times (e.g. repetition) are NOT deleted."""
    chunk = _make_chunk("c1", 0.0, 20.0, 0.0, 20.0)
    t = ChunkTranscript(
        chunk_id="c1",
        raw_text="đi nhanh đi",
        words=[
            TimedWord(text="đi", start_sec=1.0, end_sec=2.0),
            TimedWord(text="nhanh", start_sec=3.0, end_sec=4.0),
            TimedWord(text="đi", start_sec=6.0, end_sec=7.0),
        ],
        status="transcribed",
    )

    stitched = stitch_chunks([t], [chunk])

    assert [w.text for w in stitched.words] == ["đi", "nhanh", "đi"]
    assert stitched.discarded_overlap_count == 0


def test_timestamp_inversion_generates_warning() -> None:
    """Inverted timestamps generate a warning in stitched transcript."""
    chunk = _make_chunk("c1", 0.0, 20.0, 0.0, 20.0)
    t = ChunkTranscript(
        chunk_id="c1",
        raw_text="lỗi thứ tự",
        words=[
            TimedWord(text="thứ", start_sec=5.0, end_sec=6.0),
            TimedWord(text="lỗi", start_sec=2.0, end_sec=3.0),
        ],
        status="transcribed",
    )

    stitched = stitch_chunks([t], [chunk])

    # After sort, words should be ordered by start_sec [2.0, 5.0]
    assert [w.text for w in stitched.words] == ["lỗi", "thứ"]
