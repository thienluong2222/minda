"""Transcript fusion baselines F0 to F6.

Specification: Section 13.1 of docs/PLAN_VIVOS_SYNTHETIC_PIPELINE.md.
"""

from __future__ import annotations

from typing import Any

import jiwer
import numpy as np

from meeting_pipeline.domain.contracts import SourceHypothesis
from meeting_pipeline.fusion.alignment import ABSTAIN_TOKEN, EPSILON_TOKEN
from meeting_pipeline.fusion.confusion_network import ConfusionBin
from meeting_pipeline.fusion.model import LearnedFusionModel


def fuse_f0_fixed(
    source_hypotheses: dict[str, SourceHypothesis],
    fixed_source_id: str | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Baseline F0_FIXED: pick transcript from a fixed pre-designated source."""
    if not source_hypotheses:
        return "", []
    f_id = (
        fixed_source_id
        if fixed_source_id in source_hypotheses
        else sorted(source_hypotheses.keys())[0]
    )
    hyp = source_hypotheses[f_id]
    tokens = hyp.text.split()
    decisions = [
        {
            "word": tok,
            "confidence": hyp.transcript_quality_score,
            "supporting_sources": [f_id],
            "representative_source_id": f_id,
        }
        for tok in tokens
    ]
    return hyp.text, decisions


def fuse_f1_best_segment(
    source_hypotheses: dict[str, SourceHypothesis],
) -> tuple[str, list[dict[str, Any]]]:
    """Baseline F1_BEST_SEGMENT: pick transcript from source with best transcript score."""
    if not source_hypotheses:
        return "", []
    best_id = max(
        source_hypotheses.keys(),
        key=lambda k: source_hypotheses[k].transcript_quality_score,
    )
    hyp = source_hypotheses[best_id]
    tokens = hyp.text.split()
    decisions = [
        {
            "word": tok,
            "confidence": hyp.transcript_quality_score,
            "supporting_sources": [best_id],
            "representative_source_id": best_id,
        }
        for tok in tokens
    ]
    return hyp.text, decisions


def fuse_f2_oracle_best(
    source_hypotheses: dict[str, SourceHypothesis],
    reference_text: str,
) -> tuple[str, list[dict[str, Any]]]:
    """Baseline F2_ORACLE_BEST: pick source with lowest CER against reference (upper-bound only)."""
    if not source_hypotheses:
        return "", []

    def get_cer(hyp_text: str) -> float:
        return float(jiwer.cer(reference_text or " ", hyp_text or " "))

    best_id = min(source_hypotheses.keys(), key=lambda k: get_cer(source_hypotheses[k].text))
    hyp = source_hypotheses[best_id]
    tokens = hyp.text.split()
    decisions = [
        {
            "word": tok,
            "confidence": 1.0,
            "supporting_sources": [best_id],
            "representative_source_id": best_id,
        }
        for tok in tokens
    ]
    return hyp.text, decisions


def fuse_f3_rover(
    bins: list[ConfusionBin],
) -> tuple[str, list[dict[str, Any]]]:
    """Baseline F3_ROVER: unweighted majority voting across confusion network bins."""
    chosen_words: list[str] = []
    decisions: list[dict[str, Any]] = []

    for b in bins:
        # Count token votes (excluding epsilon and abstain)
        vote_counts: dict[str, int] = {}
        source_support: dict[str, list[str]] = {}

        for src_id, token in b.candidates.items():
            if token == ABSTAIN_TOKEN:
                continue
            vote_counts[token] = vote_counts.get(token, 0) + 1
            source_support.setdefault(token, []).append(src_id)

        if not vote_counts:
            continue

        # Winner
        # Prefer deletion on a tie. With two devices, a token supported by only
        # one source is weak evidence and is a common ASR hallucination pattern.
        winner_token = max(
            vote_counts.keys(),
            key=lambda token: (vote_counts[token], token == EPSILON_TOKEN),
        )
        if winner_token != EPSILON_TOKEN:
            chosen_words.append(winner_token)
            total_eligible = sum(1 for tok in b.candidates.values() if tok != ABSTAIN_TOKEN)
            conf = float(vote_counts[winner_token] / max(total_eligible, 1))
            decisions.append(
                {
                    "word": winner_token,
                    "confidence": round(conf, 3),
                    "supporting_sources": source_support[winner_token],
                    "representative_source_id": source_support[winner_token][0],
                }
            )

    return " ".join(chosen_words), decisions


def fuse_f4_asr_weighted(
    bins: list[ConfusionBin],
) -> tuple[str, list[dict[str, Any]]]:
    """Baseline F4_ASR_WEIGHTED: voting weighted solely by token ASR confidence."""
    chosen_words: list[str] = []
    decisions: list[dict[str, Any]] = []

    for b in bins:
        weighted_votes: dict[str, float] = {}
        source_support: dict[str, list[str]] = {}

        for src_id, token in b.candidates.items():
            if token == ABSTAIN_TOKEN:
                continue
            raw_conf = b.confidences.get(src_id, 0.5)
            conf = 1.0 - raw_conf if token == EPSILON_TOKEN else raw_conf
            weighted_votes[token] = weighted_votes.get(token, 0.0) + conf
            source_support.setdefault(token, []).append(src_id)

        if not weighted_votes:
            continue

        winner_token = max(weighted_votes.keys(), key=lambda t: weighted_votes[t])
        if winner_token != EPSILON_TOKEN:
            chosen_words.append(winner_token)
            total_v = sum(weighted_votes.values())
            conf = float(weighted_votes[winner_token] / max(total_v, 1e-6))
            decisions.append(
                {
                    "word": winner_token,
                    "confidence": round(conf, 3),
                    "supporting_sources": source_support[winner_token],
                    "representative_source_id": max(
                        source_support[winner_token],
                        key=lambda s: b.confidences.get(s, 0.0),
                    ),
                }
            )

    return " ".join(chosen_words), decisions


def fuse_f5_rule_weighted(
    bins: list[ConfusionBin],
) -> tuple[str, list[dict[str, Any]]]:
    """Baseline F5_RULE_WEIGHTED: voting weighted by acoustic + ASR transcript quality scores."""
    chosen_words: list[str] = []
    decisions: list[dict[str, Any]] = []

    for b in bins:
        weighted_votes: dict[str, float] = {}
        source_support: dict[str, list[str]] = {}

        for src_id, token in b.candidates.items():
            if token == ABSTAIN_TOKEN:
                continue
            # A missing token is a real vote, not a zero-weight placeholder.
            # This prevents a single hallucinating source from injecting long
            # unsupported spans into the fused transcript.
            q_score = b.source_scores.get(src_id, 0.5)
            asr_c = b.confidences.get(src_id, 0.5)
            token_confidence = 1.0 - asr_c if token == EPSILON_TOKEN else asr_c
            w = float(q_score * token_confidence)

            weighted_votes[token] = weighted_votes.get(token, 0.0) + w
            source_support.setdefault(token, []).append(src_id)

        if not weighted_votes:
            continue

        winner_token = max(weighted_votes.keys(), key=lambda t: weighted_votes[t])
        if winner_token != EPSILON_TOKEN:
            chosen_words.append(winner_token)
            total_v = sum(weighted_votes.values())
            conf = float(weighted_votes[winner_token] / max(total_v, 1e-6))
            rep_src = max(
                source_support[winner_token],
                key=lambda s: b.source_scores.get(s, 0.0) * b.confidences.get(s, 0.0),
            )
            decisions.append(
                {
                    "word": winner_token,
                    "confidence": round(conf, 3),
                    "supporting_sources": source_support[winner_token],
                    "representative_source_id": rep_src,
                }
            )

    return " ".join(chosen_words), decisions


def fuse_f5_rule_weighted_corrected(
    bins: list[ConfusionBin],
    source_hypotheses: dict[str, SourceHypothesis] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Corrected F5 rule-weighted fusion: protects best source from unverified hallucinations."""
    chosen_words: list[str] = []
    decisions: list[dict[str, Any]] = []

    best_source_id: str | None = None
    if source_hypotheses:
        transcribed_sources = {
            sid: hyp for sid, hyp in source_hypotheses.items() if hyp.asr_status == "transcribed"
        }
        if transcribed_sources:
            best_source_id = max(
                transcribed_sources.keys(),
                key=lambda s: transcribed_sources[s].transcript_quality_score,
            )

    for b in bins:
        weighted_votes: dict[str, float] = {}
        source_support: dict[str, list[str]] = {}

        for src_id, token in b.candidates.items():
            if token == ABSTAIN_TOKEN:
                continue

            q_score = b.source_scores.get(src_id, 0.5)
            asr_c = b.confidences.get(src_id, 0.5)
            token_confidence = 1.0 - asr_c if token == EPSILON_TOKEN else asr_c
            w = float(q_score * token_confidence)

            weighted_votes[token] = weighted_votes.get(token, 0.0) + w
            source_support.setdefault(token, []).append(src_id)

        if not weighted_votes:
            continue

        candidate_winner = max(weighted_votes.keys(), key=lambda t: weighted_votes[t])

        # Local best source for this bin if global not available
        eligible_sources = [s for s, tok in b.candidates.items() if tok != ABSTAIN_TOKEN]
        if not eligible_sources:
            continue

        b_best_src = (
            best_source_id
            if (best_source_id and best_source_id in eligible_sources)
            else max(eligible_sources, key=lambda s: b.source_scores.get(s, 0.0))
        )
        best_src_token = b.candidates.get(b_best_src, EPSILON_TOKEN)

        winner_token = candidate_winner
        needs_review = False
        # If candidate_winner disagrees with best source, require strong consensus
        if best_src_token in weighted_votes and candidate_winner != best_src_token:
            best_vote = weighted_votes.get(best_src_token, 0.0)
            cand_vote = weighted_votes.get(candidate_winner, 0.0)
            margin = cand_vote - best_vote
            supporters = source_support.get(candidate_winner, [])

            if best_src_token == EPSILON_TOKEN:
                # Primary source is silent. Only accept candidate token
                # if it beats epsilon by margin >= 0.15
                if margin >= 0.15:
                    winner_token = candidate_winner
                else:
                    winner_token = EPSILON_TOKEN
                    needs_review = True
            elif candidate_winner == EPSILON_TOKEN:
                # Primary source has a word, other sources want to delete it.
                # Only delete if margin >= 0.15 AND at least 2 sources agree to delete.
                if margin >= 0.15 and len(supporters) >= 2:
                    winner_token = EPSILON_TOKEN
                else:
                    winner_token = best_src_token
                    needs_review = True
            else:
                # Primary source has word A, candidate is word B.
                # Only switch if candidate beats primary by >= 0.15 AND has at least 2 supporters.
                if margin >= 0.15 and len(supporters) >= 2:
                    winner_token = candidate_winner
                else:
                    winner_token = best_src_token
                    needs_review = True

        if winner_token != EPSILON_TOKEN:
            chosen_words.append(winner_token)
            total_v = sum(weighted_votes.values())
            conf = float(weighted_votes[winner_token] / max(total_v, 1e-6))
            rep_src = (
                max(
                    source_support[winner_token],
                    key=lambda s: b.source_scores.get(s, 0.0) * b.confidences.get(s, 0.0),
                )
                if source_support.get(winner_token)
                else b_best_src
            )
            decisions.append(
                {
                    "word": winner_token,
                    "confidence": round(conf, 3),
                    "supporting_sources": source_support.get(winner_token, [rep_src]),
                    "representative_source_id": rep_src,
                    "needs_review": needs_review or (winner_token != candidate_winner),
                }
            )

    return " ".join(chosen_words), decisions


def fuse_f6_learned(
    bins: list[ConfusionBin],
    learned_model: LearnedFusionModel,
) -> tuple[str, list[dict[str, Any]]]:
    """Baseline F6_LEARNED: token correctness predicted via Logistic Regression model."""
    chosen_words: list[str] = []
    decisions: list[dict[str, Any]] = []

    num_sources = len(bins[0].candidates) if bins else 1

    for b in bins:
        token_candidate_scores: dict[str, float] = {}
        source_support: dict[str, list[str]] = {}

        for src_id, token in b.candidates.items():
            if token == EPSILON_TOKEN:
                # Epsilon score is inverted confidence
                eps_score = b.source_scores.get(src_id, 0.5) * (
                    1.0 - b.confidences.get(src_id, 0.5)
                )
                token_candidate_scores[EPSILON_TOKEN] = (
                    token_candidate_scores.get(EPSILON_TOKEN, 0.0) + eps_score
                )
                source_support.setdefault(EPSILON_TOKEN, []).append(src_id)
                continue

            # Feature vector: [audio_quality, asr_conf, no_speech, agreement, len, dur]
            audio_q = b.source_scores.get(src_id, 0.5)
            asr_c = b.confidences.get(src_id, 0.8)
            agreement = sum(1 for tok in b.candidates.values() if tok == token) / max(
                num_sources, 1
            )
            feats = np.array(
                [audio_q, asr_c, 0.05, agreement, float(len(token)), 0.3],
                dtype=np.float32,
            )

            pred_proba = learned_model.predict_token_score(feats)
            token_candidate_scores[token] = token_candidate_scores.get(token, 0.0) + pred_proba
            source_support.setdefault(token, []).append(src_id)

        winner_token = max(
            token_candidate_scores.keys(),
            key=lambda t: token_candidate_scores[t],
        )
        if winner_token != EPSILON_TOKEN:
            chosen_words.append(winner_token)
            total_s = sum(token_candidate_scores.values())
            conf = float(token_candidate_scores[winner_token] / max(total_s, 1e-6))
            rep_src = max(
                source_support[winner_token],
                key=lambda s: b.confidences.get(s, 0.0),
            )
            decisions.append(
                {
                    "word": winner_token,
                    "confidence": round(conf, 3),
                    "supporting_sources": source_support[winner_token],
                    "representative_source_id": rep_src,
                }
            )

    return " ".join(chosen_words), decisions
