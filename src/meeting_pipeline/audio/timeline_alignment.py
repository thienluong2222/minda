"""Resolve clip clocks without inventing elapsed time between disconnected parts."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from itertools import pairwise
from typing import Any

from meeting_pipeline.audio.fingerprints import (
    AcousticMap,
    Array,
    Fingerprint,
    candidate_pairs,
    match_fingerprints,
    refine_maps,
)


@dataclass
class ClockSpan:
    clip_id: str
    clock_id: str
    start: float
    end: float
    scale: float
    offset: float
    origin: str
    residual_ms: float | None = None
    anchors: int = 0
    via: tuple[str, ...] = ()
    boundary_uncertainty_ms: float | None = None

    def at(self, time: float) -> float:
        return self.scale * time + self.offset


def local_clock(clip_id: str, start: float = 0.0) -> str:
    key = f"{clip_id}:{start:.6f}"
    return "part-" + hashlib.sha256(key.encode()).hexdigest()[:12]


def resolve_clocks(
    layout: dict[str, Any],
    durations: dict[str, float],
    features: dict[str, Fingerprint],
    load: Callable[[str], Array],
    sample_rate: int,
    minimum_common_sec: float = 3.0,
    check: Callable[[], None] | None = None,
    maximum_extrapolation_sec: float = 120.0,
) -> dict[str, Any]:
    clips: dict[str, dict[str, Any]] = {clip["id"]: clip for clip in layout["clips"]}
    predecessors: dict[str, str | None] = {
        clip_id: (track["clip_ids"][index - 1] if index else None)
        for track in layout["tracks"]
        for index, clip_id in enumerate(track["clip_ids"])
    }
    spans: dict[str, list[ClockSpan]] = {}
    for clip_id, clip in clips.items():
        placement = clip["placement"]
        anchored = placement["kind"] == "anchored"
        spans[clip_id] = [
            ClockSpan(
                clip_id,
                "meeting" if anchored else local_clock(clip_id),
                0.0,
                durations[clip_id],
                1.0,
                placement["start_ms"] / 1000 if anchored else 0.0,
                "declared" if anchored else "local",
                via=(clip_id,),
            )
        ]
    roots = [clip_id for clip_id in clips if clips[clip_id]["placement"]["kind"] == "anchored"]
    reference_root = None
    if not roots:
        first_parts = [track["clip_ids"][0] for track in layout["tracks"] if track["clip_ids"]]
        reference_root = min(first_parts, key=lambda key: (-durations[key], key))
        spans[reference_root][0] = replace(
            spans[reference_root][0], clock_id="meeting", origin="reference"
        )

    def propagate() -> None:
        for _ in range(len(clips)):
            changed = False
            for clip_id, clip in clips.items():
                placement = clip["placement"]
                previous = predecessors[clip_id]
                if (
                    placement["kind"] != "sequential"
                    or previous is None
                    or placement["gap_before_ms"] is None
                    or any(piece.origin in {"acoustic", "extrapolated"} for piece in spans[clip_id])
                ):
                    continue
                last = spans[previous][-1]
                if clip_id in last.via:
                    continue
                expected = last.at(durations[previous]) + placement["gap_before_ms"] / 1000
                value = ClockSpan(
                    clip_id,
                    last.clock_id,
                    0,
                    durations[clip_id],
                    1.0,
                    expected,
                    "sequential",
                    via=(*last.via, clip_id),
                )
                if asdict(spans[clip_id][0]) != asdict(value) or len(spans[clip_id]) != 1:
                    spans[clip_id] = [value]
                    changed = True
            if not changed:
                break

    propagate()

    pairs = candidate_pairs(features)
    pair_maps: dict[tuple[str, str], list[AcousticMap]] = {}
    for left, right in pairs:
        if check:
            check()
        # Prefer the longer recording as a search reference, not as proof of time.
        reference, query = sorted((left, right), key=lambda key: (-durations[key], key))
        maps = match_fingerprints(features[reference], features[query], minimum_common_sec)
        if maps:
            maps = refine_maps(maps, load(reference), load(query), sample_rate)
            pair_maps[(reference, query)] = maps
            pair_maps[(query, reference)] = [mapping.inverse() for mapping in maps]

    conflicts: list[dict[str, Any]] = []
    # Initial declared starts remain authoritative; audio changes are proposals
    # when they disagree. Acyclic evidence paths prevent self-confirmation.
    for _ in range(max(1, len(clips))):
        changed = False
        for (reference, query), maps in pair_maps.items():
            if query == reference_root:
                if any(
                    (b.scale * b.start + b.offset) - (a.scale * b.start + a.offset) > 0.18
                    for a, b in pairwise(maps)
                ):
                    conflicts.append({"clip_id": query, "reason": "reference_has_discontinuity"})
                continue
            proposals = []
            for mapping in maps:
                for source in spans[reference]:
                    if query in source.via:
                        continue
                    start = max(mapping.start, (source.start - mapping.offset) / mapping.scale)
                    end = min(mapping.end, (source.end - mapping.offset) / mapping.scale)
                    if end - start < 0.1:
                        continue
                    proposals.append(
                        ClockSpan(
                            query,
                            source.clock_id,
                            start,
                            end,
                            source.scale * mapping.scale,
                            source.scale * mapping.offset + source.offset,
                            "extrapolated" if source.origin == "extrapolated" else "acoustic",
                            None if source.origin == "extrapolated" else mapping.residual_ms,
                            mapping.anchors,
                            (*source.via, query),
                            mapping.boundary_uncertainty_ms,
                        )
                    )
            if not proposals:
                continue
            proposals.sort(key=lambda value: value.start)
            # Conflicting paths or nonmonotone steps are never force-combined.
            if any(
                b.start < a.end - 0.001
                or (a.clock_id == b.clock_id and b.at(b.start) < a.at(a.end) - 0.05)
                for a, b in pairwise(proposals)
            ):
                conflicts.append({"clip_id": query, "reason": "nonmonotone_audio_matches"})
                continue
            current = spans[query]
            if any(value.clock_id == "meeting" for value in current) and not any(
                value.clock_id == "meeting" for value in proposals
            ):
                continue
            placement = clips[query]["placement"]
            previous_id = predecessors[query]
            expected = None
            if placement["kind"] == "anchored":
                expected = ("meeting", placement["start_ms"] / 1000)
            elif placement["gap_before_ms"] is not None and previous_id is not None:
                prev = spans[previous_id][-1]
                expected = (
                    prev.clock_id,
                    prev.at(durations[previous_id]) + placement["gap_before_ms"] / 1000,
                )
            if (
                expected
                and proposals[0].start < 0.01
                and (
                    proposals[0].clock_id != expected[0]
                    or abs(proposals[0].offset - expected[1]) > 0.12
                )
            ):
                conflicts.append(
                    {
                        "clip_id": query,
                        "reason": "declared_start_conflicts_with_audio",
                        "declared_start_sec": expected[1],
                        "proposed_start_sec": proposals[0].offset,
                    }
                )
                continue
            if (
                placement["kind"] == "anchored"
                and proposals[0].start >= 0.01
                and (
                    proposals[0].clock_id != "meeting"
                    or abs(
                        proposals[0].at(proposals[0].start)
                        - (placement["start_ms"] / 1000 + proposals[0].start)
                    )
                    > 0.12
                )
            ):
                conflicts.append({"clip_id": query, "reason": "declared_start_not_supported"})
                continue
            old_coverage = sum(
                value.end - value.start
                for value in current
                if value.origin == "acoustic" and value.clock_id == "meeting"
            )
            new_coverage = sum(
                value.end - value.start for value in proposals if value.clock_id == "meeting"
            )
            if old_coverage >= new_coverage - 0.001 and any(
                value.origin == "acoustic" for value in current
            ):
                # Independent paths still need to agree with accepted evidence.
                for value in proposals:
                    for old in current:
                        point = max(value.start, old.start)
                        if (
                            old.origin == "acoustic"
                            and min(value.end, old.end) > point
                            and value.clock_id == old.clock_id
                            and abs(value.at(point) - old.at(point)) > 0.12
                        ):
                            conflicts.append(
                                {"clip_id": query, "reason": "inconsistent_audio_paths"}
                            )
                continue
            covered = []
            cursor = 0.0
            reference_pieces = spans[reference]
            first_reference = reference_pieces[0]
            reference_affine = all(
                value.clock_id == first_reference.clock_id
                and abs(value.scale - first_reference.scale) < 1e-8
                and abs(value.offset - first_reference.offset) < 1e-6
                for value in reference_pieces
            )
            affine_edge = (
                len(maps) == 1
                and reference_affine
                and all(
                    value.clock_id == proposals[0].clock_id
                    and abs(value.scale - proposals[0].scale) < 1e-8
                    and abs(value.offset - proposals[0].offset) < 1e-6
                    for value in proposals
                )
            )
            for proposal in proposals:
                if proposal.start > cursor + 1e-6:
                    if affine_edge and proposal.start <= maximum_extrapolation_sec:
                        covered.append(
                            replace(
                                proposal,
                                start=cursor,
                                end=proposal.start,
                                origin="extrapolated",
                                residual_ms=None,
                            )
                        )
                    else:
                        covered.append(
                            ClockSpan(
                                query,
                                local_clock(query, cursor),
                                cursor,
                                proposal.start,
                                1.0,
                                -cursor,
                                "local",
                                via=(query,),
                            )
                        )
                covered.append(proposal)
                cursor = proposal.end
            if cursor < durations[query] - 1e-6:
                if affine_edge and durations[query] - cursor <= maximum_extrapolation_sec:
                    covered.append(
                        replace(
                            proposals[-1],
                            start=cursor,
                            end=durations[query],
                            origin="extrapolated",
                            residual_ms=None,
                        )
                    )
                else:
                    covered.append(
                        ClockSpan(
                            query,
                            local_clock(query, cursor),
                            cursor,
                            durations[query],
                            1.0,
                            -cursor,
                            "local",
                            via=(query,),
                        )
                    )
            if [asdict(v) for v in covered] != [asdict(v) for v in current]:
                spans[query] = covered
                changed = True
        propagate()
        if not changed:
            break

    # Check declared order without inferring a gap length from order alone.
    for clip_id, previous in predecessors.items():
        if previous is not None:
            earlier, later = spans[previous][-1], spans[clip_id][0]
            if (
                earlier.clock_id == later.clock_id
                and earlier.at(earlier.end) > later.at(later.start) + 0.05
            ):
                conflicts.append({"clip_id": clip_id, "reason": "recording_order_conflict"})
    conflicts = list({str(sorted(value.items())): value for value in conflicts}.values())
    components = sorted(
        {span.clock_id for values in spans.values() for span in values},
        key=lambda clock: (clock != "meeting", clock),
    )
    return {
        "schema_version": 1,
        "algorithm": "landmark_peaks_piecewise_v1",
        "spans": {key: [asdict(value) for value in values] for key, values in spans.items()},
        "timing_complete": components == ["meeting"] and not conflicts,
        "clock_ids": components,
        "conflicts": conflicts,
        "candidate_pairs": len(pairs),
        "matched_pairs": len(pair_maps) // 2,
        "reference_clip_id": reference_root,
        "clock_basis": "declared" if roots else "reference_recording",
    }
