"""Chunk planning with core ownership and context expansion."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import numpy as np

from meeting_pipeline.config import AsrConfig
from meeting_pipeline.domain.schemas import Interval
from meeting_pipeline.domain.transcription import AsrChunk, SpeechRegion

if TYPE_CHECKING:
    pass


def find_optimal_boundary(
    audio: np.ndarray,
    sample_rate: int,
    start_sec: float,
    search_center_sec: float,
    search_radius_sec: float,
    frame_ms: int = 20,
) -> float:
    """Find the local energy minimum within a search window around a target time."""
    win_start = max(start_sec, search_center_sec - search_radius_sec)
    win_end = search_center_sec + search_radius_sec
    total_audio_sec = audio.size / sample_rate
    win_end = min(total_audio_sec, win_end)

    if win_end <= win_start:
        return search_center_sec

    start_sample = int(win_start * sample_rate)
    end_sample = int(win_end * sample_rate)
    window_audio = audio[start_sample:end_sample]

    frame_samples = max(1, int(sample_rate * frame_ms / 1000.0))
    usable = window_audio.size - window_audio.size % frame_samples
    if usable <= 0:
        return search_center_sec

    frames = window_audio[:usable].reshape(-1, frame_samples)
    energy = np.mean(np.square(frames, dtype=np.float64), axis=1)

    min_frame_idx = int(np.argmin(energy))
    best_time = win_start + (min_frame_idx * frame_samples + frame_samples / 2) / sample_rate
    return round(float(best_time), 4)


def plan_region_chunks(
    region: SpeechRegion,
    asr_config: AsrConfig,
    meeting_duration: float,
    audio_samples: np.ndarray | None = None,
    sample_rate: int = 16000,
    source_id: str | None = None,
) -> list[AsrChunk]:
    """Plan AsrChunks with disjoint core intervals and context-expanded clips."""
    selected_source = source_id or (
        region.supporting_source_ids[0] if region.supporting_source_ids else "source-1"
    )

    max_chunk_sec = float(asr_config.max_chunk_seconds)
    target_core_sec = float(asr_config.target_core_seconds)
    context_sec = float(asr_config.chunk_context_seconds)
    search_radius_sec = float(asr_config.boundary_search_seconds)

    # 1. Determine core intervals
    core_boundaries: list[float] = [region.start_sec]
    current_start = region.start_sec

    while True:
        remaining_duration = region.end_sec - current_start
        if remaining_duration <= max_chunk_sec + 1e-6:
            # The remainder fits in one chunk
            core_boundaries.append(region.end_sec)
            break

        # Long region: find split point near current_start + target_core_sec
        nominal_split = current_start + target_core_sec

        if audio_samples is not None and audio_samples.size > 0:
            split_point = find_optimal_boundary(
                audio=audio_samples,
                sample_rate=sample_rate,
                start_sec=current_start + 1.0,  # ensure at least 1s progress
                search_center_sec=nominal_split,
                search_radius_sec=search_radius_sec,
            )
            # Ensure split_point makes forward progress and doesn't exceed bounds
            split_point = max(current_start + 1.0, min(region.end_sec - 1.0, split_point))
        else:
            split_point = round(nominal_split, 4)

        core_boundaries.append(split_point)
        current_start = split_point

    # 2. Build AsrChunk models
    chunks: list[AsrChunk] = []
    for idx in range(len(core_boundaries) - 1):
        core_start = core_boundaries[idx]
        core_end = core_boundaries[idx + 1]

        # Context expansion
        clip_start = max(0.0, core_start - context_sec)
        clip_end = min(meeting_duration, core_end + context_sec)

        # Enforce max_chunk_seconds limit on clip
        clip_duration = clip_end - clip_start
        if clip_duration > max_chunk_sec:
            excess = clip_duration - max_chunk_sec
            # Trim context from ends while preserving core
            can_trim_start = core_start - clip_start
            can_trim_end = clip_end - core_end
            total_can_trim = can_trim_start + can_trim_end

            if total_can_trim > 0:
                trim_start = excess * (can_trim_start / total_can_trim)
                trim_end = excess * (can_trim_end / total_can_trim)
                clip_start = min(core_start, clip_start + trim_start)
                clip_end = max(core_end, clip_end - trim_end)
            else:
                clip_start = core_start
                clip_end = core_end

        chunk_id = f"chunk-{uuid.uuid4()}"
        chunk = AsrChunk(
            chunk_id=chunk_id,
            region_id=region.region_id,
            source_id=selected_source,
            core_interval=Interval(
                start_sec=round(core_start, 4),
                end_sec=round(core_end, 4),
            ),
            clip_interval=Interval(
                start_sec=round(clip_start, 4),
                end_sec=round(clip_end, 4),
            ),
            clip_artifact_id=f"clips/asr-input/{chunk_id}.wav",
        )
        chunks.append(chunk)

    return chunks


class ChunkPlanner:
    """Plan and validate AsrChunk allocations across all meeting SpeechRegions."""

    def __init__(self, config: AsrConfig, sample_rate: int = 16000) -> None:
        self.config = config
        self.sample_rate = sample_rate

    def plan(
        self,
        regions: list[SpeechRegion],
        meeting_duration: float,
        source_audio_map: dict[str, np.ndarray] | None = None,
        preferred_source_map: dict[str, str] | None = None,
    ) -> list[AsrChunk]:
        """Generate verified AsrChunk list adhering strictly to invariant requirements."""
        all_chunks: list[AsrChunk] = []

        for region in regions:
            selected_source = (
                preferred_source_map.get(region.region_id) if preferred_source_map else None
            )
            audio = (
                source_audio_map.get(selected_source)
                if (source_audio_map and selected_source)
                else None
            )

            region_chunks = plan_region_chunks(
                region=region,
                asr_config=self.config,
                meeting_duration=meeting_duration,
                audio_samples=audio,
                sample_rate=self.sample_rate,
                source_id=selected_source,
            )

            # Invariant verifications
            self._verify_invariants(region, region_chunks, meeting_duration)
            all_chunks.extend(region_chunks)

        return all_chunks

    def _verify_invariants(
        self,
        region: SpeechRegion,
        chunks: list[AsrChunk],
        meeting_duration: float,
    ) -> None:
        """Verify the four formal invariants mandated by Section 7.3."""
        if not chunks:
            raise ValueError(f"Region {region.region_id} produced no chunks")

        tolerance = 1.0 / self.sample_rate  # 1 sample tolerance (0.0625 ms)

        # 1. union(core_intervals) == speech_region
        if abs(chunks[0].core_interval.start_sec - region.start_sec) > tolerance:
            raise ValueError("First chunk core does not match region start")
        if abs(chunks[-1].core_interval.end_sec - region.end_sec) > tolerance:
            raise ValueError("Last chunk core does not match region end")

        for idx in range(len(chunks) - 1):
            gap = chunks[idx + 1].core_interval.start_sec - chunks[idx].core_interval.end_sec
            if abs(gap) > tolerance:
                raise ValueError(
                    f"Gap or overlap {gap} detected between chunk cores {idx} and {idx + 1}"
                )

        # 2. clip_duration <= max_chunk_seconds
        max_sec = float(self.config.max_chunk_seconds)
        for chunk in chunks:
            clip_dur = chunk.clip_interval.end_sec - chunk.clip_interval.start_sec
            if clip_dur > max_sec + tolerance:
                raise ValueError(
                    f"Chunk {chunk.chunk_id} clip duration {clip_dur} exceeds max {max_sec}"
                )

            # 3. core_interval within clip_interval
            if chunk.core_interval.start_sec < chunk.clip_interval.start_sec - tolerance:
                raise ValueError(f"Core starts before clip in chunk {chunk.chunk_id}")
            if chunk.core_interval.end_sec > chunk.clip_interval.end_sec + tolerance:
                raise ValueError(f"Core ends after clip in chunk {chunk.chunk_id}")

            # 4. bounds clamp
            if chunk.clip_interval.start_sec < -tolerance:
                raise ValueError(f"Clip starts before 0 in chunk {chunk.chunk_id}")
            if chunk.clip_interval.end_sec > meeting_duration + tolerance:
                raise ValueError(f"Clip exceeds meeting duration in chunk {chunk.chunk_id}")
