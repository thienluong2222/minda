"""Speaker-turn boundaries from pyannote segmentation after shared VAD.

Pyannote's ``Inference`` converts the seven powerset classes to three local
multi-label channels. Channels are permutation invariant between windows and
sources; they must be matched across overlapping windows before making turns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import permutations
from pathlib import Path
from typing import Any

import numpy as np

from meeting_pipeline.adapters.pyannote_segmentation import PyannoteSegmentationAdapter
from meeting_pipeline.domain.contracts import MeetingSegment


@dataclass(slots=True)
class SpeakerTurn:
    turn_id: str
    speech_region_id: str
    start_sec: float
    end_sec: float
    track_id: str
    speaker_count: int
    overlap_group_id: str | None = None
    supporting_source_ids: list[str] = field(default_factory=list)
    source_activity: dict[str, dict[str, Any]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "turn_id": self.turn_id,
            "speech_region_id": self.speech_region_id,
            "start_sec": self.start_sec,
            "end_sec": self.end_sec,
            "track_id": self.track_id,
            "speaker_count": self.speaker_count,
            "overlap_group_id": self.overlap_group_id,
            "supporting_source_ids": self.supporting_source_ids,
            "source_activity": self.source_activity,
            "warnings": self.warnings,
        }


class SpeakerTurnDetector:
    """Detect contiguous one/two-speaker intervals on the synchronized clock."""

    def __init__(
        self,
        checkpoint: Path,
        step_seconds: float,
        adapter: PyannoteSegmentationAdapter | None = None,
        bin_sec: float = 0.05,
    ) -> None:
        self.adapter = adapter or PyannoteSegmentationAdapter(checkpoint, step_seconds)
        self.bin_sec = bin_sec

    def detect(
        self,
        aligned_paths: dict[str, Path],
        segments: list[MeetingSegment],
        reference_source: str,
        duration_sec: float,
        cached_results: dict[str, Any] | None = None,
    ) -> list[SpeakerTurn]:
        if not segments:
            return []
        if reference_source not in aligned_paths:
            raise ValueError("Reference source is missing for speaker-turn detection")
        num_bins = max(1, int(np.ceil(duration_sec / self.bin_sec)))

        def _get_seg(source_id: str, path: Path) -> Any:
            if cached_results and source_id in cached_results:
                return cached_results[source_id]
            try:
                return self.adapter.segment_file(path, source_id=source_id)
            except TypeError:
                return self.adapter.segment_file(path)

        tracks_by_source = {
            source_id: self._decode(_get_seg(source_id, path), num_bins)
            for source_id, path in aligned_paths.items()
        }
        reference = tracks_by_source[reference_source]
        turns: list[SpeakerTurn] = []
        for segment in segments:
            first = max(0, int(np.floor(segment.start_sec / self.bin_sec)))
            last = min(num_bins, int(np.ceil(segment.end_sec / self.bin_sec)))
            if last <= first:
                continue
            states: list[tuple[str, ...]] = []
            supporters: list[list[str]] = []
            for bin_index in range(first, last):
                source_count = {
                    source_id: int(np.count_nonzero(matrix[bin_index]))
                    for source_id, matrix in tracks_by_source.items()
                }
                active = [f"local-{j + 1}" for j in np.flatnonzero(reference[bin_index])]
                active = active[:2]
                observed = min(2, max(source_count.values(), default=0))
                while len(active) < observed:
                    active.append(f"unresolved-{segment.segment_id}-{len(active) + 1}")
                # Segmentation can report no speaker inside a padded VAD region.
                # Do not turn those silent frames into a fabricated speaker turn.
                states.append(tuple(active))
                supporters.append([sid for sid, count in source_count.items() if count > 0])

            # Reject one-frame flips without shifting a sustained speaker boundary.
            states = _smooth_states(states, minimum_bins=max(2, round(0.25 / self.bin_sec)))
            run_start = 0
            for index in range(1, len(states) + 1):
                if index < len(states) and states[index] == states[run_start]:
                    continue
                start = max(segment.start_sec, (first + run_start) * self.bin_sec)
                end = min(segment.end_sec, (first + index) * self.bin_sec)
                if end - start >= 0.15 and states[run_start]:
                    labels = states[run_start]
                    group_id = (
                        f"{segment.segment_id}-overlap-{run_start}" if len(labels) == 2 else None
                    )
                    support = sorted(
                        {sid for group in supporters[run_start:index] for sid in group}
                    )
                    for label in labels:
                        activity = {
                            sid: source_activity_for_turn(matrix, start, end, self.bin_sec)
                            for sid, matrix in tracks_by_source.items()
                        }
                        turns.append(
                            SpeakerTurn(
                                turn_id=f"turn_{len(turns):04d}",
                                speech_region_id=segment.segment_id,
                                start_sec=round(start, 3),
                                end_sec=round(end, 3),
                                track_id=label,
                                speaker_count=len(labels),
                                overlap_group_id=group_id,
                                supporting_source_ids=support,
                                source_activity=activity,
                                warnings=(
                                    ["speaker_track_unresolved"]
                                    if label.startswith("unresolved")
                                    else []
                                ),
                            )
                        )
                run_start = index
        return turns

    def _decode(self, scores: Any, num_bins: int) -> np.ndarray[Any, np.dtype[np.bool_]]:
        data = np.asarray(scores.data)
        if data.ndim != 3 or data.shape[2] != 3:
            raise ValueError(
                "Expected pyannote Inference's three decoded multilabel channels; "
                f"received {data.shape}"
            )
        chunk_window = scores.sliding_window
        chunk_duration = float(chunk_window.duration)
        # The first/last 1.25 seconds of an overlapping chunk are less reliable.
        frame_step = chunk_duration / max(1, data.shape[1])
        stitched = np.zeros((num_bins, data.shape[2]), dtype=np.float32)
        votes = np.zeros((num_bins, data.shape[2]), dtype=np.float32)
        previous: np.ndarray[Any, np.dtype[np.float32]] | None = None
        previous_start = 0.0
        next_track = 0
        local_to_global: dict[int, int] = {}
        for chunk_index, chunk in enumerate(data):
            chunk_start = float(chunk_window[chunk_index].start)
            local = (chunk >= 0.5).astype(np.float32)
            if previous is None:
                local_to_global = {}
                for j in range(local.shape[1]):
                    if np.any(local[:, j]):
                        local_to_global[j] = next_track
                        next_track += 1
                    else:
                        local_to_global[j] = -1
            else:
                # Match speakers only in the shared time span; labels are arbitrary per chunk.
                overlap_start = max(previous_start, chunk_start)
                overlap_end = min(previous_start + chunk_duration, chunk_start + chunk_duration)
                sample_times = np.arange(overlap_start + 0.1, overlap_end - 0.1, self.bin_sec)
                prior_idx = np.clip(
                    ((sample_times - previous_start) / frame_step).astype(int),
                    0,
                    len(previous) - 1,
                )
                curr_idx = np.clip(
                    ((sample_times - chunk_start) / frame_step).astype(int),
                    0,
                    len(local) - 1,
                )
                prior = previous[prior_idx]
                current = local[curr_idx]
                similarity = prior.T @ current if len(sample_times) else np.zeros((3, 3))
                match = max(
                    permutations(range(3)),
                    key=lambda p: sum(similarity[i, p[i]] for i in range(3)),
                )
                new_mapping: dict[int, int] = {}
                for previous_label, current_label in enumerate(match):
                    if not np.any(local[:, current_label]):
                        new_mapping[current_label] = -1
                        continue
                    intersection = float(similarity[previous_label, current_label])
                    union = float(
                        np.count_nonzero(prior[:, previous_label])
                        + np.count_nonzero(current[:, current_label])
                        - intersection
                    )
                    if (
                        union > 0
                        and intersection / union >= 0.25
                        and local_to_global[previous_label] >= 0
                    ):
                        new_mapping[current_label] = local_to_global[previous_label]
                    else:
                        new_mapping[current_label] = next_track
                        next_track += 1
                local_to_global = new_mapping
            for frame_index, frame in enumerate(local):
                t_start = chunk_start + frame_index * frame_step
                t_end = chunk_start + (frame_index + 1) * frame_step
                start_bin = max(0, int(t_start / self.bin_sec))
                end_bin = min(num_bins, max(start_bin + 1, int(np.ceil(t_end / self.bin_sec))))
                if start_bin >= num_bins or end_bin <= 0:
                    continue
                for local_id, value in enumerate(frame):
                    global_id = local_to_global[local_id]
                    if global_id < 0:
                        continue
                    if global_id >= stitched.shape[1]:
                        grow = global_id + 1 - stitched.shape[1]
                        stitched = np.pad(stitched, ((0, 0), (0, grow)))
                        votes = np.pad(votes, ((0, 0), (0, grow)))
                    for b in range(start_bin, end_bin):
                        stitched[b, global_id] += value
                        votes[b, global_id] += 1
            previous = local
            previous_start = chunk_start
        return np.divide(stitched, votes, out=np.zeros_like(stitched), where=votes > 0) >= 0.5


def _smooth_states(states: list[tuple[str, ...]], minimum_bins: int) -> list[tuple[str, ...]]:
    result = states.copy()
    i = 0
    while i < len(result):
        j = i + 1
        while j < len(result) and result[j] == result[i]:
            j += 1
        if j - i < minimum_bins and i > 0 and j < len(result) and result[i - 1] == result[j]:
            result[i:j] = [result[i - 1]] * (j - i)
        i = j
    return result


def source_activity_for_turn(
    matrix: np.ndarray, start_sec: float, end_sec: float, bin_sec: float
) -> dict[str, Any]:
    """Measure per-source active speech, local multi-speaker occupancy and intervals."""
    first = max(0, int(np.floor(start_sec / bin_sec)))
    last = min(len(matrix), int(np.ceil(end_sec / bin_sec)))
    counts = np.count_nonzero(matrix[first:last], axis=1)
    active = counts > 0
    support_sec = float(np.count_nonzero(active) * bin_sec)
    duration = max(end_sec - start_sec, 1e-8)
    intervals: list[list[float]] = []
    begin: int | None = None
    for offset, is_active in enumerate([*active, False]):
        if is_active and begin is None:
            begin = offset
        elif not is_active and begin is not None:
            intervals.append(
                [
                    round(max(start_sec, (first + begin) * bin_sec), 3),
                    round(min(end_sec, (first + offset) * bin_sec), 3),
                ]
            )
            begin = None
    return {
        "speech_seconds": round(support_sec, 3),
        "speech_coverage": round(min(1.0, support_sec / duration), 3),
        "local_speaker_purity": (
            round(float(np.count_nonzero(counts == 1) / np.count_nonzero(active)), 3)
            if np.any(active)
            else None
        ),
        "supporting_source": support_sec >= 0.2,
        "support_duration_sec": round(support_sec, 3),
        "speech_intervals": intervals,
    }
