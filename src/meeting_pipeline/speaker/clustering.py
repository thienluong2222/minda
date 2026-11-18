"""Global speaker clustering and open-set identification across a full meeting.

Specification: Section 2 & WP2 of docs/PLAN_VAD_SPEAKER_ASR_MULTI_SOURCE_2026-10-03.md.
Implements two-pass offline clustering (seed pass + assignment pass) with cannot-link
overlap constraints, stable anonymous speaker ordinals, and open-set profile matching.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from meeting_pipeline.application.speakers import SpeakerProfileInput
from meeting_pipeline.audio.coverage import (
    intersect_recorded,
    interval_metadata,
    recorded_intervals,
)
from meeting_pipeline.pipeline.speaker_turns import SpeakerTurn
from meeting_pipeline.speaker.encoder import (
    BaseSpeakerEncoder,
    ECAPAEncoder,
    WeSpeakerEncoder,
)
from meeting_pipeline.speaker.source_quality import (
    SpeakerFusionPolicy,
    compute_normalized_source_weights,
    evaluate_source_quality_for_speaker_id,
    fuse_turn_candidate_scores,
    fuse_turn_speaker_embeddings,
)

logger = logging.getLogger(__name__)


def _cannot_link(left: SpeakerTurn, right: SpeakerTurn) -> bool:
    """Local tracks imply different voices only where both are active concurrently."""
    overlap = min(left.end_sec, right.end_sec) - max(left.start_sec, right.start_sec)
    return (
        overlap >= 0.05
        and left.speaker_count == right.speaker_count == 1
        and left.track_id != right.track_id
        and not left.track_id.startswith("unresolved")
        and not right.track_id.startswith("unresolved")
        and left.speech_region_id == right.speech_region_id
    )


def _constrained_groups(
    turns: list[SpeakerTurn], embeddings: dict[str, np.ndarray], max_distance: float
) -> list[list[str]]:
    """Average-link clustering with a hard pairwise cannot-link at every merge."""
    groups = [[turn.turn_id] for turn in turns]
    lookup = {turn.turn_id: turn for turn in turns}
    while len(groups) > 1:
        best: tuple[float, int, int] | None = None
        for i, left in enumerate(groups):
            for j in range(i + 1, len(groups)):
                right = groups[j]
                if any(_cannot_link(lookup[a], lookup[b]) for a in left for b in right):
                    continue
                distance = float(
                    np.mean(
                        [
                            1.0 - float(np.dot(embeddings[a], embeddings[b]))
                            for a in left
                            for b in right
                        ]
                    )
                )
                if distance <= max_distance and (best is None or distance < best[0]):
                    best = (distance, i, j)
        if best is None:
            break
        _, i, j = best
        groups[i].extend(groups[j])
        del groups[j]
    return groups


def _merge_sparse_seed_groups(
    groups: list[list[str]],
    turns: dict[str, SpeakerTurn],
    embeddings: dict[str, np.ndarray],
    similarity_threshold: float,
    margin_threshold: float,
) -> list[list[str]]:
    """Attach small seed islands to a multi-turn anchor only with distinctive evidence."""
    anchors = [group for group in groups if len(group) >= 3]
    sparse = [group for group in groups if len(group) < 3]
    for group in sparse:
        vector = np.mean(np.stack([embeddings[tid] for tid in group]), axis=0)
        vector /= max(float(np.linalg.norm(vector)), 1e-8)
        ranked: list[tuple[float, int]] = []
        for index, anchor in enumerate(anchors):
            if any(_cannot_link(turns[a], turns[b]) for a in group for b in anchor):
                continue
            centroid = np.mean(np.stack([embeddings[tid] for tid in anchor]), axis=0)
            centroid /= max(float(np.linalg.norm(centroid)), 1e-8)
            ranked.append((float(np.dot(vector, centroid)), index))
        ranked.sort(reverse=True)
        if (
            ranked
            and ranked[0][0] >= similarity_threshold
            and (len(ranked) == 1 or ranked[0][0] - ranked[1][0] >= margin_threshold)
        ):
            anchors[ranked[0][1]].extend(group)
        else:
            anchors.append(group)
    return anchors


def _confident_top(scores: dict[str, float], threshold: float, margin: float) -> str | None:
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if not ranked:
        return None
    runner_up = ranked[1][1] if len(ranked) > 1 else -1.0
    if ranked[0][1] >= threshold and ranked[0][1] - runner_up >= margin:
        return ranked[0][0]
    return None


@dataclass(slots=True)
class ClusterDecision:
    """Cluster-level identity decision matching or creating anonymous identity."""

    cluster_id: str
    meeting_speaker_id: str
    speaker_id: str | None
    speaker_label: str
    speaker_status: str  # "identified" | "unknown"
    turn_ids: list[str] = field(default_factory=list)
    total_speech_seconds: float = 0.0
    centroid: np.ndarray | None = None
    top_candidates: list[dict[str, Any]] = field(default_factory=list)
    match_score: float | None = None
    match_margin: float | None = None
    decision_reason: str = ""
    anonymous_ordinal: int | None = None
    first_seen_sec: float = 0.0
    supporting_sources: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "meeting_speaker_id": self.meeting_speaker_id,
            "speaker_id": self.speaker_id,
            "speaker_label": self.speaker_label,
            "speaker_status": self.speaker_status,
            "turn_ids": self.turn_ids,
            "total_speech_seconds": round(self.total_speech_seconds, 3),
            "match_score": (round(self.match_score, 3) if self.match_score is not None else None),
            "match_margin": (
                round(self.match_margin, 3) if self.match_margin is not None else None
            ),
            "decision_reason": self.decision_reason,
            "anonymous_ordinal": self.anonymous_ordinal,
            "first_seen_sec": round(self.first_seen_sec, 3),
            "supporting_sources": self.supporting_sources,
            "top_candidates": self.top_candidates,
            "warnings": self.warnings,
        }


@dataclass(slots=True)
class TurnAssignment:
    """Turn-level assignment to a cluster and identity label."""

    turn_id: str
    cluster_id: str | None
    meeting_speaker_id: str | None
    speaker_id: str | None
    speaker_label: str
    speaker_status: str  # "identified" | "unknown" | "ambiguous"
    match_score: float | None = None
    top_candidates: list[dict[str, Any]] = field(default_factory=list)
    decision_reason: str = ""
    source_evidence: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    needs_review: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "cluster_id": self.cluster_id,
            "meeting_speaker_id": self.meeting_speaker_id,
            "speaker_id": self.speaker_id,
            "speaker_label": self.speaker_label,
            "speaker_status": self.speaker_status,
            "match_score": round(self.match_score, 3) if self.match_score is not None else None,
            "top_candidates": self.top_candidates,
            "decision_reason": self.decision_reason,
            "source_evidence": self.source_evidence,
            "warnings": self.warnings,
            "needs_review": self.needs_review,
        }


class GlobalSpeakerClusterer:
    """Multi-source offline global clustering and identification."""

    def __init__(
        self,
        encoder: BaseSpeakerEncoder | ECAPAEncoder | WeSpeakerEncoder,
        cluster_threshold: float = 0.40,
        assign_threshold: float = 0.35,
        assign_margin: float = 0.05,
        enrolled_match_threshold: float = 0.45,
        enrolled_margin: float = 0.08,
        min_seed_duration_sec: float = 0.8,
        fusion_policy: SpeakerFusionPolicy = SpeakerFusionPolicy.P2_EMBEDDING_FUSION,
        ablate_quality_feature: str | None = None,
        sync_residual_gate_ms: float = 20.0,
        local_purity_gate: float = 0.8,
        disagreement_min_weight: float = 0.25,
        dominant_source_weight: float = 0.70,
        dominant_source_gap: float = 0.35,
    ) -> None:
        self.encoder = encoder
        self.cluster_threshold = cluster_threshold
        self.assign_threshold = assign_threshold
        self.assign_margin = assign_margin
        self.enrolled_match_threshold = enrolled_match_threshold
        self.enrolled_margin = enrolled_margin
        self.min_seed_duration_sec = min_seed_duration_sec
        self.fusion_policy = fusion_policy
        self.ablate_quality_feature = ablate_quality_feature
        self.sync_residual_gate_ms = sync_residual_gate_ms
        self.local_purity_gate = local_purity_gate
        self.disagreement_min_weight = disagreement_min_weight
        self.dominant_source_weight = dominant_source_weight
        self.dominant_source_gap = dominant_source_gap

    def _extract_turn_embedding(
        self,
        turn: SpeakerTurn,
        aligned_signals: dict[str, np.ndarray],
        sample_rate: int,
        sync_metadata: dict[str, dict[str, Any]] | None = None,
        profiles: list[SpeakerProfileInput] | None = None,
    ) -> tuple[np.ndarray | None, list[dict[str, Any]], dict[str, np.ndarray]]:
        """Extract multi-source quality-weighted embedding and source evidence for a turn."""
        if turn.speaker_count != 1:
            return None, [], {}

        # Interior crop 0.05s at boundaries to avoid edge bleed
        edge_crop = 0.05
        dur = turn.end_sec - turn.start_sec
        if dur < edge_crop * 2:
            start_s = turn.start_sec
            end_s = turn.end_sec
        else:
            start_s = turn.start_sec + edge_crop
            end_s = turn.end_sec - edge_crop

        evaluations: dict[str, Any] = {}
        source_embs: dict[str, np.ndarray] = {}

        for source_id, signal in aligned_signals.items():
            sync = (sync_metadata or {}).get(source_id, {})
            activity = turn.source_activity.get(source_id, {})
            sync = interval_metadata(sync, start_s, end_s)
            coverage = sync.get("valid_coverage_interval")
            common = intersect_recorded(
                [(start_s, end_s)], recorded_intervals(sync, (start_s, end_s))
            )
            coverage_fraction = sum(b - a for a, b in common) / max(end_s - start_s, 1e-8)
            covered_start, covered_end = max(
                common, key=lambda pair: pair[1] - pair[0], default=(start_s, start_s)
            )
            coverage = [covered_start, covered_end]
            intervals = activity.get("speech_intervals") or []
            valid_intervals = [
                (max(covered_start, float(row[0])), min(covered_end, float(row[1])))
                for row in intervals
            ]
            valid_intervals = [(a, b) for a, b in valid_intervals if b > a]
            if valid_intervals:
                crop_start, crop_end = max(valid_intervals, key=lambda pair: pair[1] - pair[0])
                crop_start += min(0.05, (crop_end - crop_start) / 10)
                crop_end -= min(0.05, (crop_end - crop_start) / 10)
            else:
                crop_start, crop_end = covered_start, covered_start
            clip = signal[
                max(0, int(crop_start * sample_rate)) : min(
                    len(signal), int(crop_end * sample_rate)
                )
            ]

            q_res = evaluate_source_quality_for_speaker_id(
                source_id=source_id,
                turn_waveform=clip,
                sample_rate=sample_rate,
                full_signal=signal,
                turn_start_sec=crop_start,
                turn_end_sec=crop_end,
                sync_status=sync.get("status"),
                vad_coverage=activity.get("speech_coverage"),
                purity=activity.get("local_speaker_purity"),
                valid_coverage_interval=coverage,
                local_sync_residual_ms=sync.get("local_residual_ms", sync.get("residual_ms")),
                support_duration_sec=activity.get("support_duration_sec"),
                coverage_fraction=coverage_fraction,
                ablate_quality_feature=self.ablate_quality_feature,
                residual_gate_ms=self.sync_residual_gate_ms,
                purity_gate=self.local_purity_gate,
            )
            evaluations[source_id] = q_res

            if not q_res.is_eligible:
                continue

            min_samples = int(0.5 * sample_rate)
            padded = clip
            if len(padded) < min_samples:
                padded = np.pad(padded, (0, min_samples - len(padded)))

            try:
                emb = self.encoder.encode(padded)
                source_embs[source_id] = emb
                q_res.embedding_status = "encoded"
            except Exception as exc:
                q_res.is_eligible = False
                q_res.exclusion_reason = f"encoding_failed: {exc}"
                q_res.embedding_status = "failed"
                logger.debug(
                    "Failed to encode turn %s source %s: %s",
                    turn.turn_id,
                    source_id,
                    exc,
                )

        weights = compute_normalized_source_weights(evaluations)
        if self.fusion_policy == SpeakerFusionPolicy.P0_FIXED_REFERENCE:
            selected = next(
                (
                    sid
                    for sid in source_embs
                    if (sync_metadata or {}).get(sid, {}).get("status") == "reference"
                ),
                None,
            )
            weights = {selected: 1.0} if selected else {}
        elif self.fusion_policy == SpeakerFusionPolicy.P1_TOP1_QUALITY and source_embs:
            best = max(source_embs, key=lambda sid: evaluations[sid].identity_quality_score)
            weights = {best: 1.0}
        for sid, w in weights.items():
            evaluations[sid].identity_weight = w

        if profiles and self.fusion_policy == SpeakerFusionPolicy.P3_WEIGHTED_SCORE_FUSION:
            for sid in weights:
                evaluations[sid].candidate_cosine_scores = {
                    profile.speaker_id: round(float(np.dot(source_embs[sid], profile.embedding)), 4)
                    for profile in profiles
                }

        source_evidence_list = [evaluations[sid].as_dict() for sid in evaluations]

        if not source_embs or not weights:
            return None, source_evidence_list, source_embs

        if self.fusion_policy == SpeakerFusionPolicy.P0_FIXED_REFERENCE:
            ref_id = next(iter(weights))
            return source_embs[ref_id], source_evidence_list, source_embs

        if self.fusion_policy == SpeakerFusionPolicy.P1_TOP1_QUALITY:
            best_sid = next(iter(weights))
            return source_embs[best_sid], source_evidence_list, source_embs

        fused = fuse_turn_speaker_embeddings(source_embs, weights)
        return fused, source_evidence_list, source_embs

    def cluster_and_identify(
        self,
        turns: list[SpeakerTurn],
        aligned_signals: dict[str, np.ndarray],
        sample_rate: int,
        profiles: list[SpeakerProfileInput],
        sync_metadata: dict[str, dict[str, Any]] | None = None,
    ) -> tuple[dict[str, TurnAssignment], list[ClusterDecision], dict[str, Any]]:
        """Run two-pass clustering and matching across full meeting turns."""
        single_speaker_turns = [t for t in turns if t.speaker_count == 1]
        turn_embeddings: dict[str, np.ndarray] = {}
        turn_evidences: dict[str, list[dict[str, Any]]] = {}
        turn_source_embeddings: dict[str, dict[str, np.ndarray]] = {}

        for turn in single_speaker_turns:
            emb, evidence, source_embeddings = self._extract_turn_embedding(
                turn, aligned_signals, sample_rate, sync_metadata, profiles
            )
            turn_evidences[turn.turn_id] = evidence
            turn_source_embeddings[turn.turn_id] = source_embeddings
            if emb is not None:
                turn_embeddings[turn.turn_id] = emb

        # Pass 1: Seed selection (turns >= min_seed_duration_sec with valid embedding)
        seed_turns = [
            t
            for t in single_speaker_turns
            if t.turn_id in turn_embeddings
            and (t.end_sec - t.start_sec) >= self.min_seed_duration_sec
        ]

        clusters: list[list[str]] = []
        if len(seed_turns) == 1:
            clusters = [[seed_turns[0].turn_id]]
        elif len(seed_turns) > 1:
            clusters = _constrained_groups(seed_turns, turn_embeddings, self.cluster_threshold)
            clusters = _merge_sparse_seed_groups(
                clusters,
                {turn.turn_id: turn for turn in seed_turns},
                turn_embeddings,
                self.assign_threshold,
                self.assign_margin,
            )
        else:
            # Fallback when all turns are short (< min_seed_duration_sec)
            for t in single_speaker_turns:
                if t.turn_id in turn_embeddings:
                    clusters.append([t.turn_id])

        # Compute robust centroid for each cluster
        cluster_centroids: list[np.ndarray] = []
        cluster_turn_ids: list[list[str]] = []

        for group in clusters:
            embs = [turn_embeddings[tid] for tid in group if tid in turn_embeddings]
            if not embs:
                continue
            centroid = np.mean(np.stack(embs), axis=0)
            norm = float(np.linalg.norm(centroid))
            if norm > 1e-8:
                centroid /= norm
            cluster_centroids.append(centroid.astype(np.float32))
            cluster_turn_ids.append(list(group))

        # Pass 2: Assignment of non-seed single turns
        turn_to_cluster: dict[str, int] = {}
        for c_idx, tids in enumerate(cluster_turn_ids):
            for tid in tids:
                turn_to_cluster[tid] = c_idx

        turn_dict = {t.turn_id: t for t in turns}
        unassigned = [
            t
            for t in single_speaker_turns
            if t.turn_id not in turn_to_cluster and t.turn_id in turn_embeddings
        ]

        ambiguous_turns: set[str] = set()
        for turn in unassigned:
            emb = turn_embeddings[turn.turn_id]
            if not cluster_centroids:
                # Create a new single-turn cluster
                cluster_centroids.append(emb)
                cluster_turn_ids.append([turn.turn_id])
                turn_to_cluster[turn.turn_id] = len(cluster_centroids) - 1
                continue

            sims = [
                float(np.dot(emb, c))
                if not any(_cannot_link(turn, turn_dict[tid]) for tid in cluster_turn_ids[i])
                else -1.0
                for i, c in enumerate(cluster_centroids)
            ]
            best_idx = int(np.argmax(sims))
            best_sim = sims[best_idx]
            runner_up = sorted(sims, reverse=True)[1] if len(sims) > 1 else -1.0
            margin = best_sim - runner_up

            if best_sim >= self.assign_threshold and margin >= self.assign_margin:
                turn_to_cluster[turn.turn_id] = best_idx
                cluster_turn_ids[best_idx].append(turn.turn_id)
            else:
                ambiguous_turns.add(turn.turn_id)

        # Match clusters against enrolled speaker profiles
        cluster_decisions: list[ClusterDecision] = []
        for c_idx, c_turns in enumerate(cluster_turn_ids):
            centroid = cluster_centroids[c_idx]
            total_sec = sum(
                (turn_dict[tid].end_sec - turn_dict[tid].start_sec)
                for tid in c_turns
                if tid in turn_dict
            )
            first_seen = min(
                (turn_dict[tid].start_sec for tid in c_turns if tid in turn_dict),
                default=0.0,
            )
            sources = sorted(
                {
                    sid
                    for tid in c_turns
                    if tid in turn_dict
                    for sid in turn_dict[tid].supporting_source_ids
                }
            )

            # Match against enrolled profiles
            conflict = False
            policy_notes: list[str] = []
            if self.fusion_policy == SpeakerFusionPolicy.P3_WEIGHTED_SCORE_FUSION and profiles:
                totals = {profile.speaker_id: 0.0 for profile in profiles}
                turn_weight_total = 0.0
                for tid in c_turns:
                    evidence_by_source = {
                        str(row["source_id"]): row for row in turn_evidences.get(tid, [])
                    }
                    weights = {
                        sid: float(row["identity_weight"])
                        for sid, row in evidence_by_source.items()
                        if float(row["identity_weight"]) > 0
                    }
                    source_scores = {
                        sid: {
                            profile.speaker_id: float(np.dot(vector, profile.embedding))
                            for profile in profiles
                        }
                        for sid, vector in turn_source_embeddings.get(tid, {}).items()
                        if sid in weights
                    }
                    strong = sorted(
                        (
                            (sid, weights[sid])
                            for sid in source_scores
                            if weights[sid] >= self.disagreement_min_weight
                        ),
                        key=lambda item: item[1],
                        reverse=True,
                    )
                    if len(strong) >= 2:
                        first_top = _confident_top(
                            source_scores[strong[0][0]],
                            self.enrolled_match_threshold,
                            self.enrolled_margin,
                        )
                        second_top = _confident_top(
                            source_scores[strong[1][0]],
                            self.enrolled_match_threshold,
                            self.enrolled_margin,
                        )
                        if first_top and second_top and first_top != second_top:
                            if (
                                strong[0][1] >= self.dominant_source_weight
                                and strong[0][1] - strong[1][1] >= self.dominant_source_gap
                            ):
                                source_scores = {strong[0][0]: source_scores[strong[0][0]]}
                                weights = {strong[0][0]: 1.0}
                                policy_notes.append(f"dominant_source_top1:{strong[0][0]}")
                            else:
                                conflict = True
                                policy_notes.append(f"source_disagreement:{tid}")
                    per_turn = fuse_turn_candidate_scores(source_scores, weights)
                    if per_turn:
                        turn_weight = min(3.0, turn_dict[tid].end_sec - turn_dict[tid].start_sec)
                        for profile_id, score in per_turn.items():
                            totals[profile_id] += score * turn_weight
                        turn_weight_total += turn_weight
                score_by_id = {
                    profile_id: total / turn_weight_total
                    for profile_id, total in totals.items()
                    if turn_weight_total > 0
                }
                ranked = sorted(
                    (
                        (p, score_by_id[p.speaker_id])
                        for p in profiles
                        if p.speaker_id in score_by_id
                    ),
                    key=lambda item: item[1],
                    reverse=True,
                )
            else:
                ranked = sorted(
                    ((p, float(np.dot(centroid, p.embedding))) for p in profiles),
                    key=lambda item: item[1],
                    reverse=True,
                )
            candidates = [
                {
                    "speaker_id": p.speaker_id,
                    "display_name": p.display_name,
                    "cosine_score": round(score, 3),
                }
                for p, score in ranked[:3]
            ]

            match_score = ranked[0][1] if ranked else None
            runner_up = ranked[1][1] if len(ranked) > 1 else -1.0
            match_margin = (match_score - runner_up) if match_score is not None else None

            if conflict:
                decision = ClusterDecision(
                    cluster_id=f"c-{c_idx + 1:04d}",
                    meeting_speaker_id="",
                    speaker_id=None,
                    speaker_label="Chưa xác định",
                    speaker_status="ambiguous",
                    turn_ids=c_turns,
                    total_speech_seconds=total_sec,
                    centroid=centroid,
                    top_candidates=candidates,
                    match_score=match_score,
                    match_margin=match_margin,
                    decision_reason=";".join(policy_notes),
                    first_seen_sec=first_seen,
                    supporting_sources=sources,
                    warnings=["source_disagreement"],
                )
            elif (
                match_score is not None
                and match_margin is not None
                and match_score >= self.enrolled_match_threshold
                and match_margin >= self.enrolled_margin
            ):
                matched_profile = ranked[0][0]
                policy_label = (
                    "P3_score_fusion"
                    if self.fusion_policy == SpeakerFusionPolicy.P3_WEIGHTED_SCORE_FUSION
                    else "enrolled_match"
                )
                decision = ClusterDecision(
                    cluster_id=f"c-{c_idx + 1:04d}",
                    meeting_speaker_id="",  # will assign below
                    speaker_id=matched_profile.speaker_id,
                    speaker_label=matched_profile.display_name,
                    speaker_status="identified",
                    turn_ids=c_turns,
                    total_speech_seconds=total_sec,
                    centroid=centroid,
                    top_candidates=candidates,
                    match_score=match_score,
                    match_margin=match_margin,
                    decision_reason=(
                        f"{policy_label}: score={match_score:.3f} "
                        f">= {self.enrolled_match_threshold:.2f}, "
                        f"margin={match_margin:.3f} >= {self.enrolled_margin:.2f}; "
                        f"{';'.join(policy_notes)}"
                    ),
                    first_seen_sec=first_seen,
                    supporting_sources=sources,
                )
            else:
                if not ranked:
                    reason = "no_enrolled_profiles"
                elif match_score is not None and match_score < self.enrolled_match_threshold:
                    thresh = self.enrolled_match_threshold
                    reason = f"enrolled_rejected: score={match_score:.3f} < {thresh:.2f}"
                else:
                    margin_val = match_margin if match_margin is not None else 0.0
                    reason = f"low_margin: margin={margin_val:.3f} < {self.enrolled_margin:.2f}"
                decision = ClusterDecision(
                    cluster_id=f"c-{c_idx + 1:04d}",
                    meeting_speaker_id="",
                    speaker_id=None,
                    speaker_label="",
                    speaker_status="unknown",
                    turn_ids=c_turns,
                    total_speech_seconds=total_sec,
                    centroid=centroid,
                    top_candidates=candidates,
                    match_score=match_score,
                    match_margin=match_margin,
                    decision_reason=reason,
                    first_seen_sec=first_seen,
                    supporting_sources=sources,
                )
            cluster_decisions.append(decision)

        # Stable meeting_speaker_id and anonymous speaker ordinals
        # Sort anonymous clusters by first_seen_sec, then cluster_id to break ties
        unknown_clusters = [cd for cd in cluster_decisions if cd.speaker_status == "unknown"]
        unknown_clusters.sort(key=lambda cd: (cd.first_seen_sec, cd.cluster_id))
        for ord_idx, cd in enumerate(unknown_clusters, start=1):
            cd.anonymous_ordinal = ord_idx
            cd.speaker_label = f"Người lạ {ord_idx}"

        # Assign opaque meeting_speaker_id (ms-0001, ms-0002, ...) sorted by first_seen_sec
        all_sorted = sorted(cluster_decisions, key=lambda cd: (cd.first_seen_sec, cd.cluster_id))
        for ms_idx, cd in enumerate(all_sorted, start=1):
            cd.meeting_speaker_id = f"ms-{ms_idx:04d}"

        # Build final TurnAssignment mapping
        assignments: dict[str, TurnAssignment] = {}
        for turn in turns:
            tid = turn.turn_id
            if turn.speaker_count == 2:
                # Overlap turns remain unassigned to individual speakers
                assignments[tid] = TurnAssignment(
                    turn_id=tid,
                    cluster_id=None,
                    meeting_speaker_id=None,
                    speaker_id=None,
                    speaker_label="Nói chồng",
                    speaker_status="ambiguous",
                    decision_reason="overlap_not_run",
                    source_evidence=turn_evidences.get(tid, []),
                    warnings=["simultaneous_speech"],
                    needs_review=True,
                )
            elif tid in ambiguous_turns or tid not in turn_to_cluster:
                assignments[tid] = TurnAssignment(
                    turn_id=tid,
                    cluster_id=None,
                    meeting_speaker_id=None,
                    speaker_id=None,
                    speaker_label="Chưa xác định",
                    speaker_status="ambiguous",
                    decision_reason="insufficient_cluster_evidence",
                    source_evidence=turn_evidences.get(tid, []),
                    warnings=["ambiguous_speaker_evidence"],
                    needs_review=True,
                )
            else:
                c_idx = turn_to_cluster[tid]
                cd = cluster_decisions[c_idx]
                assignments[tid] = TurnAssignment(
                    turn_id=tid,
                    cluster_id=cd.cluster_id,
                    meeting_speaker_id=cd.meeting_speaker_id,
                    speaker_id=cd.speaker_id,
                    speaker_label=cd.speaker_label,
                    speaker_status=cd.speaker_status,
                    match_score=cd.match_score,
                    top_candidates=cd.top_candidates,
                    decision_reason=cd.decision_reason,
                    source_evidence=turn_evidences.get(tid, []),
                    warnings=list(cd.warnings),
                    needs_review=cd.speaker_status == "ambiguous",
                )

        cluster_summary = {
            "schema_version": "2.0",
            "speaker_fusion_policy": self.fusion_policy.value,
            "quality_formula_version": "speaker_q_v3",
            "calibration_status": "unvalidated",
            "total_clusters": len(cluster_decisions),
            "identified_count": sum(
                1 for cd in cluster_decisions if cd.speaker_status == "identified"
            ),
            "unknown_count": len(unknown_clusters),
            "ambiguous_turns_count": len(ambiguous_turns),
            "ambiguous_cluster_turns_count": sum(
                len(cd.turn_ids) for cd in cluster_decisions if cd.speaker_status == "ambiguous"
            ),
            "clusters": [cd.as_dict() for cd in cluster_decisions],
        }

        return assignments, cluster_decisions, cluster_summary
