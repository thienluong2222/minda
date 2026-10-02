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
from sklearn.cluster import AgglomerativeClustering  # type: ignore[import-untyped]

from meeting_pipeline.application.speakers import SpeakerProfileInput
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
    fuse_turn_speaker_embeddings,
)

logger = logging.getLogger(__name__)


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
    ) -> None:
        self.encoder = encoder
        self.cluster_threshold = cluster_threshold
        self.assign_threshold = assign_threshold
        self.assign_margin = assign_margin
        self.enrolled_match_threshold = enrolled_match_threshold
        self.enrolled_margin = enrolled_margin
        self.min_seed_duration_sec = min_seed_duration_sec
        self.fusion_policy = fusion_policy

    def _extract_turn_embedding(
        self,
        turn: SpeakerTurn,
        aligned_signals: dict[str, np.ndarray],
        sample_rate: int,
    ) -> tuple[np.ndarray | None, list[dict[str, Any]]]:
        """Extract multi-source quality-weighted embedding and source evidence for a turn."""
        if turn.speaker_count != 1:
            return None, []

        # Interior crop 0.05s at boundaries to avoid edge bleed
        edge_crop = 0.05
        dur = turn.end_sec - turn.start_sec
        if dur < edge_crop * 2:
            start_s = turn.start_sec
            end_s = turn.end_sec
        else:
            start_s = turn.start_sec + edge_crop
            end_s = turn.end_sec - edge_crop

        s_sample = max(0, int(start_s * sample_rate))
        e_sample = int(end_s * sample_rate)

        evaluations: dict[str, Any] = {}
        source_embs: dict[str, np.ndarray] = {}

        for source_id, signal in aligned_signals.items():
            if len(signal) < e_sample or e_sample <= s_sample:
                continue
            clip = signal[s_sample:e_sample]
            if len(clip) == 0:
                continue

            q_res = evaluate_source_quality_for_speaker_id(
                source_id=source_id,
                turn_waveform=clip,
                sample_rate=sample_rate,
                full_signal=signal,
                turn_start_sec=start_s,
                turn_end_sec=end_s,
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
            except Exception as exc:
                q_res.is_eligible = False
                q_res.exclusion_reason = f"encoding_failed: {exc}"
                logger.debug(
                    "Failed to encode turn %s source %s: %s",
                    turn.turn_id,
                    source_id,
                    exc,
                )

        weights = compute_normalized_source_weights(evaluations)
        for sid, w in weights.items():
            if sid in evaluations:
                evaluations[sid].identity_weight = w

        source_evidence_list = [evaluations[sid].as_dict() for sid in evaluations]

        if not source_embs:
            return None, source_evidence_list

        if self.fusion_policy == SpeakerFusionPolicy.P0_FIXED_REFERENCE:
            ref_id = next(iter(source_embs))
            return source_embs[ref_id], source_evidence_list

        if self.fusion_policy == SpeakerFusionPolicy.P1_TOP1_QUALITY:
            best_sid = max(
                source_embs,
                key=lambda sid: evaluations[sid].identity_quality_score,
            )
            return source_embs[best_sid], source_evidence_list

        fused = fuse_turn_speaker_embeddings(source_embs, weights)
        return fused, source_evidence_list

    def cluster_and_identify(
        self,
        turns: list[SpeakerTurn],
        aligned_signals: dict[str, np.ndarray],
        sample_rate: int,
        profiles: list[SpeakerProfileInput],
    ) -> tuple[dict[str, TurnAssignment], list[ClusterDecision], dict[str, Any]]:
        """Run two-pass clustering and matching across full meeting turns."""
        single_speaker_turns = [t for t in turns if t.speaker_count == 1]
        turn_embeddings: dict[str, np.ndarray] = {}
        turn_evidences: dict[str, list[dict[str, Any]]] = {}

        for turn in single_speaker_turns:
            emb, evidence = self._extract_turn_embedding(turn, aligned_signals, sample_rate)
            turn_evidences[turn.turn_id] = evidence
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
            seed_embs = np.stack([turn_embeddings[t.turn_id] for t in seed_turns])
            # Cosine distance matrix D = 1 - (A @ A.T)
            cos_sim = np.clip(seed_embs @ seed_embs.T, -1.0, 1.0)
            dist_matrix = np.clip(1.0 - cos_sim, 0.0, 2.0)

            # Apply cannot-link constraints (turns with distinct track_id in adjacent overlap)
            for i, t_i in enumerate(seed_turns):
                for j, t_j in enumerate(seed_turns):
                    if (
                        i != j
                        and t_i.speech_region_id == t_j.speech_region_id
                        and t_i.track_id != t_j.track_id
                    ):
                        dist_matrix[i, j] = 999.0
                        dist_matrix[j, i] = 999.0

            clustering = AgglomerativeClustering(
                n_clusters=None,
                distance_threshold=self.cluster_threshold,
                metric="precomputed",
                linkage="average",
            )
            labels = clustering.fit_predict(dist_matrix)

            cluster_map: dict[int, list[str]] = {}
            for idx, label in enumerate(labels):
                cluster_map.setdefault(label, []).append(seed_turns[idx].turn_id)
            clusters = list(cluster_map.values())
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

            sims = [float(np.dot(emb, c)) for c in cluster_centroids]
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

            if (
                match_score is not None
                and match_margin is not None
                and match_score >= self.enrolled_match_threshold
                and match_margin >= self.enrolled_margin
            ):
                matched_profile = ranked[0][0]
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
                        f"enrolled_match: score={match_score:.3f} "
                        f">= {self.enrolled_match_threshold:.2f}, "
                        f"margin={match_margin:.3f} >= {self.enrolled_margin:.2f}"
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
                    needs_review=False,
                )

        cluster_summary = {
            "total_clusters": len(cluster_decisions),
            "identified_count": sum(
                1 for cd in cluster_decisions if cd.speaker_status == "identified"
            ),
            "unknown_count": len(unknown_clusters),
            "ambiguous_turns_count": len(ambiguous_turns),
            "clusters": [cd.as_dict() for cd in cluster_decisions],
        }

        return assignments, cluster_decisions, cluster_summary
