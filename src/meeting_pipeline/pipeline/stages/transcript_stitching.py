"""Transcript stitching via core ownership and boundary deduplication."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from meeting_pipeline.domain.transcription import AsrChunk, ChunkTranscript, TimedWord

if TYPE_CHECKING:
    pass

_PUNCT_RE = re.compile(r"^[^\w\s]+|[^\w\s]+$")


def _norm_token(token: str) -> str:
    """Normalize token by lowercasing and stripping leading/trailing punctuation."""
    cleaned = token.strip().lower()
    return _PUNCT_RE.sub("", cleaned)


class StitchedTranscript(BaseModel):
    """Unified chronological transcript resulting from core-ownership stitching."""

    words: list[TimedWord]
    full_text: str
    warnings: list[str] = Field(default_factory=list)
    discarded_overlap_count: int = 0


def stitch_chunks(
    chunk_transcripts: list[ChunkTranscript],
    chunks: list[AsrChunk],
) -> StitchedTranscript:
    """Apply core ownership filtering and stitch chunk transcripts into a single stream."""
    chunk_map = {chunk.chunk_id: chunk for chunk in chunks}
    kept_words: list[TimedWord] = []
    warnings: list[str] = []

    # 1. Core ownership filtering
    for ct in chunk_transcripts:
        chunk = chunk_map.get(ct.chunk_id)
        if not chunk:
            warnings.append(f"unknown_chunk_id: {ct.chunk_id}")
            continue

        core_s = chunk.core_interval.start_sec
        core_e = chunk.core_interval.end_sec

        for word in ct.words:
            midpoint = (word.start_sec + word.end_sec) / 2.0
            # Token ownership strictly belongs to the chunk whose core covers the midpoint
            if (core_s - 1e-5) <= midpoint < (core_e + 1e-5):
                kept_words.append(word)

    # 2. Stable chronological sort
    kept_words.sort(key=lambda w: (w.start_sec, w.end_sec))

    # 3. Boundary deduplication for edge artifacts
    deduped_words: list[TimedWord] = []
    discarded_count = 0

    idx = 0
    while idx < len(kept_words):
        curr_word = kept_words[idx]
        if idx + 1 < len(kept_words):
            next_word = kept_words[idx + 1]
            curr_norm = _norm_token(curr_word.text)
            next_norm = _norm_token(next_word.text)

            # Check if identical token overlapping in time or within boundary tolerance (300ms)
            is_same_text = curr_norm and (curr_norm == next_norm)
            is_adjacent_or_overlapping = next_word.start_sec <= curr_word.end_sec + 0.3

            if is_same_text and is_adjacent_or_overlapping:
                # Discard duplicate; keep the one with larger duration or confidence
                curr_dur = curr_word.end_sec - curr_word.start_sec
                next_dur = next_word.end_sec - next_word.start_sec
                chosen = next_word if next_dur > curr_dur else curr_word
                deduped_words.append(chosen)
                discarded_count += 1
                idx += 2
                continue

        deduped_words.append(curr_word)
        idx += 1

    # 4. Invariant checks: timestamps non-decreasing
    for i in range(len(deduped_words) - 1):
        if deduped_words[i + 1].start_sec < deduped_words[i].start_sec - 1e-5:
            warnings.append(
                f"timestamp_inversion: {deduped_words[i].text}@{deduped_words[i].start_sec} "
                f"> {deduped_words[i + 1].text}@{deduped_words[i + 1].start_sec}"
            )

    full_text = " ".join(w.text for w in deduped_words).strip()

    return StitchedTranscript(
        words=deduped_words,
        full_text=full_text,
        warnings=warnings,
        discarded_overlap_count=discarded_count,
    )


class TranscriptStitcher:
    """Service to stitch chunk transcripts into a clean, unified meeting transcript."""

    def stitch(
        self,
        chunk_transcripts: list[ChunkTranscript],
        chunks: list[AsrChunk],
    ) -> StitchedTranscript:
        return stitch_chunks(chunk_transcripts, chunks)
