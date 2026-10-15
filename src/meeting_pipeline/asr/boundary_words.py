"""Retain turn-edge words and reconcile only shared audio inside one speaker turn."""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

from meeting_pipeline.adapters.phowhisper_asr import AsrResult
from meeting_pipeline.data.vivos import normalize_vietnamese_text
from meeting_pipeline.domain.contracts import SourceHypothesis, WordHypothesis

BOUNDARY_POLICY_VERSION = "interval_edges_seam_alignment_v1"
DecodedChunk = tuple[dict[str, SourceHypothesis], dict[str, Any]]


def filter_boundary_words(
    result: AsrResult,
    *,
    turn_id: str,
    core: tuple[float, float],
    clip: tuple[float, float],
    internal_start: bool = False,
    internal_end: bool = False,
    end_inclusive: bool = True,
) -> tuple[list[WordHypothesis], list[dict[str, Any]]]:
    """Keep valid interval intersections at outer edges; defer internal context.

    Raw timestamps are recorded unchanged. No zero-duration timestamp is expanded
    to manufacture an overlap. Only accepted ASR results can supply candidates.
    """
    words: list[WordHypothesis] = []
    audit: list[dict[str, Any]] = []
    previous_start = previous_end = -math.inf
    for index, token in enumerate(result.words):
        text = normalize_vietnamese_text(token.text)
        start = round(clip[0] + token.start_sec, 3)
        end = round(clip[0] + token.end_sec, 3)
        midpoint = (start + end) / 2
        record: dict[str, Any] = {
            "word_index": index,
            "original_text": token.text,
            "word": text,
            "local_interval": [token.start_sec, token.end_sec],
            "absolute_interval": [start, end],
            "core_interval": list(core),
            "clip_interval": list(clip),
            "asr_confidence": token.confidence,
            "origin_turn_id": turn_id,
            "owner_turn_id": None,
            "decision": "dropped",
            "time_status": "uncertain",
        }
        audit.append(record)
        if result.status != "transcribed":
            record["reason"] = "rejected_asr_candidate"
            continue
        if not text:
            record["reason"] = "empty_word"
            continue
        if (
            not all(math.isfinite(value) for value in (start, end))
            or end < start
            or end <= 0
            or start < clip[0] - 1e-4
            or end > clip[1] + 1e-4
            or start < previous_start - 1e-4
            or end < previous_end - 1e-4
        ):
            record["reason"] = "invalid_timestamp"
            continue
        previous_start, previous_end = start, end
        owned = core[0] - 1e-4 <= midpoint and (
            midpoint <= core[1] + 1e-4 if end_inclusive else midpoint < core[1]
        )
        intersects = min(end, core[1]) - max(start, core[0]) > 1e-4
        internal_context = (midpoint < core[0] and internal_start) or (
            midpoint >= core[1] and internal_end
        )
        if end == start:
            if owned:
                record.update(
                    decision="kept", reason="degenerate_timestamp_in_core", owner_turn_id=turn_id
                )
                words.append(_word(record))
            else:
                record["reason"] = "invalid_timestamp"
            continue
        if owned:
            record.update(decision="kept", reason="midpoint_in_core", owner_turn_id=turn_id)
        elif internal_context:
            record.update(decision="deferred", reason="internal_context")
            continue
        elif intersects:
            record.update(
                decision="kept", reason="outer_boundary_intersection", owner_turn_id=turn_id
            )
        else:
            record["reason"] = "outside_core_context"
            continue
        uncertain = (
            not owned
            or start < core[0]
            or end > core[1]
            or abs(start - core[0]) < 0.05
            or abs(end - core[1]) < 0.05
        )
        record["time_status"] = "uncertain" if uncertain else "exact"
        words.append(_word(record))
    return words, audit


def _word(record: dict[str, Any]) -> WordHypothesis:
    return WordHypothesis(
        word=record["word"],
        start_sec=record["absolute_interval"][0],
        end_sec=record["absolute_interval"][1],
        asr_confidence=record["asr_confidence"],
        time_status=record["time_status"],
    )


def refresh_boundary_hypothesis(hypothesis: SourceHypothesis) -> None:
    """Recompute text/confidence and attach review warnings after ownership changes."""
    if hypothesis.asr_status != "transcribed":
        return
    hypothesis.text = " ".join(word.word for word in hypothesis.words)
    confidences = [w.asr_confidence for w in hypothesis.words if w.asr_confidence is not None]
    hypothesis.asr_features["mean_confidence"] = (
        round(sum(confidences) / len(confidences), 3) if confidences else None
    )
    warnings = hypothesis.asr_warnings
    if any(
        r.get("decision") == "kept"
        and r.get("reason") in {"outer_boundary_intersection", "internal_boundary_reassigned"}
        for r in hypothesis.word_boundary_audit
    ):
        warnings.append("asr_boundary_words_recovered")
    if any(r.get("reason") == "invalid_timestamp" for r in hypothesis.word_boundary_audit):
        warnings.append("asr_invalid_word_timestamp")
    if any(r.get("matched_turn_ids") for r in hypothesis.word_boundary_audit):
        warnings.append("asr_boundary_words_reconciled")
    if any(
        r.get("reason") == "degenerate_timestamp_in_core" for r in hypothesis.word_boundary_audit
    ):
        warnings.append("asr_word_time_uncertain")
    hypothesis.asr_warnings = list(dict.fromkeys(warnings))


@dataclass
class _Occurrence:
    chunk: int
    record: dict[str, Any]

    @property
    def midpoint(self) -> float:
        start, end = self.record["absolute_interval"]
        return float((start + end) / 2)


def _same_emission(a: _Occurrence, b: _Occurrence) -> bool:
    if a.record["word"] != b.record["word"]:
        return False
    a_start, a_end = a.record["absolute_interval"]
    b_start, b_end = b.record["absolute_interval"]
    shortest = min(a_end - a_start, b_end - b_start)
    if shortest <= 0:
        return False
    overlap = min(a_end, b_end) - max(a_start, b_start)
    # Require actual shared time and close centers, not just equal neighbouring text.
    return bool(
        overlap >= 0.5 * shortest and abs(a.midpoint - b.midpoint) <= max(0.12, shortest / 2)
    )


def _align_occurrences(
    left: list[int], right: list[int], occurrences: list[_Occurrence]
) -> list[tuple[int, int]]:
    """Monotonic LCS; minimize center distance when repeated words have equal counts."""
    scores = [[(0, 0.0) for _ in range(len(right) + 1)] for _ in range(len(left) + 1)]
    moves = [["" for _ in range(len(right) + 1)] for _ in range(len(left) + 1)]
    for i, li in enumerate(left, 1):
        for j, ri in enumerate(right, 1):
            best, move = max((scores[i - 1][j], "left"), (scores[i][j - 1], "right"))
            a, b = occurrences[li], occurrences[ri]
            if _same_emission(a, b):
                count, distance = scores[i - 1][j - 1]
                matched = (count + 1, distance - abs(a.midpoint - b.midpoint))
                if matched >= best:
                    best, move = matched, "match"
            scores[i][j], moves[i][j] = best, move
    pairs = []
    i, j = len(left), len(right)
    while i and j:
        move = moves[i][j]
        if move == "match":
            pairs.append((left[i - 1], right[j - 1]))
            i, j = i - 1, j - 1
        elif move == "left":
            i -= 1
        else:
            j -= 1
    return list(reversed(pairs))


def reconcile_internal_chunks(chunks: list[DecodedChunk]) -> None:
    """Assign each accepted acoustic occurrence once within one continuous ASR group.

    Never compare different speakers or overlap groups. Rejected/unrun source
    hypotheses remain rejected/unrun. Unowned candidates stay auditable.
    """
    if len(chunks) < 2:
        return
    group = chunks[0][1].get("asr_chunk_group_id")
    if not group or any(meta.get("asr_chunk_group_id") != group for _, meta in chunks):
        raise ValueError("Boundary reconciliation requires one ASR chunk group.")
    if any(
        abs(left[1]["core_interval"][1] - right[1]["core_interval"][0]) > 1e-4
        for left, right in pairwise(chunks)
    ):
        raise ValueError("ASR group cores must be contiguous.")
    source_ids = set().union(*(set(sources) for sources, _ in chunks))
    for source_id in sorted(source_ids):
        occurrences = [
            _Occurrence(index, record)
            for index, (sources, _) in enumerate(chunks)
            if source_id in sources and sources[source_id].asr_status == "transcribed"
            for record in sources[source_id].word_boundary_audit
            if record["decision"] in {"kept", "deferred"}
        ]
        if not occurrences:
            continue
        parents = list(range(len(occurrences)))

        members = [{o.chunk} for o in occurrences]
        for index in range(len(chunks) - 1):
            clip_left, clip_right = (
                chunks[index][1]["clip_interval"],
                chunks[index + 1][1]["clip_interval"],
            )
            shared_start = max(clip_left[0], clip_right[0])
            shared_end = min(clip_left[1], clip_right[1])
            if shared_end <= shared_start:
                continue
            candidates = [
                [
                    i
                    for i, occurrence in enumerate(occurrences)
                    if occurrence.chunk == chunk_index
                    and occurrence.record["absolute_interval"][0] < shared_end
                    and occurrence.record["absolute_interval"][1] > shared_start
                ]
                for chunk_index in (index, index + 1)
            ]
            for left, right in _align_occurrences(candidates[0], candidates[1], occurrences):
                a, b = _find_root(parents, left), _find_root(parents, right)
                if a != b and not members[a].intersection(members[b]):
                    parents[b] = a
                    members[a].update(members[b])
        groups: dict[int, list[_Occurrence]] = {}
        for index, occurrence in enumerate(occurrences):
            groups.setdefault(_find_root(parents, index), []).append(occurrence)
        for sources, _ in chunks:
            if source_id in sources and sources[source_id].asr_status == "transcribed":
                sources[source_id].words = []
        for matches in groups.values():
            _assign_occurrence(matches, chunks, source_id)
        for sources, _ in chunks:
            if source_id in sources:
                hypothesis = sources[source_id]
                hypothesis.words.sort(key=lambda word: (word.start_sec, word.end_sec))
                refresh_boundary_hypothesis(hypothesis)


def _find_root(parents: list[int], index: int) -> int:
    while parents[index] != index:
        parents[index] = parents[parents[index]]
        index = parents[index]
    return index


def _assign_occurrence(
    matches: list[_Occurrence], chunks: list[DecodedChunk], source_id: str
) -> None:
    def rank(occurrence: _Occurrence) -> tuple[float, float]:
        start, end = occurrence.record["absolute_interval"]
        core = chunks[occurrence.chunk][1]["core_interval"]
        clip = chunks[occurrence.chunk][1]["clip_interval"]
        return (
            max(0.0, min(end, core[1]) - max(start, core[0])) / max(end - start, 1e-4),
            min(start - clip[0], clip[1] - end),
        )

    already_owned = [o for o in matches if o.record["decision"] == "kept"]
    chosen = max(already_owned or matches, key=rank)
    owner = chosen.chunk
    if not already_owned:
        midpoint = chosen.midpoint
        possible = [
            i
            for i, (sources, meta) in enumerate(chunks)
            if source_id in sources
            and sources[source_id].asr_status == "transcribed"
            and meta["core_interval"][0] <= midpoint < meta["core_interval"][1]
        ]
        if not possible:
            for occurrence in matches:
                occurrence.record.update(decision="dropped", reason="owner_source_unavailable")
                chunks[occurrence.chunk][0][source_id].asr_warnings.append(
                    "asr_boundary_owner_unresolved"
                )
            return
        owner = possible[0]
    owner_turn = chunks[owner][1]["turn_id"]
    for occurrence in matches:
        occurrence.record.update(owner_turn_id=owner_turn)
        if len(matches) > 1:
            occurrence.record["matched_turn_ids"] = [chunks[o.chunk][1]["turn_id"] for o in matches]
        if occurrence is not chosen:
            occurrence.record.update(decision="deduplicated", reason="same_audio_in_adjacent_clip")
        elif owner != occurrence.chunk or not already_owned:
            occurrence.record.update(
                decision="transferred" if owner != occurrence.chunk else "kept",
                reason="internal_boundary_reassigned",
                time_status="uncertain",
            )
    record = chosen.record
    if owner != chosen.chunk:
        adopted = dict(record, decision="kept")
        chunks[owner][0][source_id].word_boundary_audit.append(adopted)
    if len(matches) > 1:
        record["time_status"] = "uncertain"
    chunks[owner][0][source_id].words.append(_word(record))
