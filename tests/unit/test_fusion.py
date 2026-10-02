import pytest

from meeting_pipeline.pipeline.stages.fuse import (
    CandidateEvidence,
    identity_weights,
    selection_weights,
)


def candidate(source_id: str, eligible: bool, quality: float, score: float) -> CandidateEvidence:
    return CandidateEvidence(source_id, eligible, quality, quality, quality, {"speaker-a": score})


def test_only_eligible_sources_receive_identity_weight() -> None:
    candidates = [candidate("a", True, 0.9, 0.8), candidate("b", False, 1.0, 0.9)]
    weights = identity_weights(candidates)
    assert weights == {"a": 1.0, "b": 0.0}


def test_all_invalid_is_insufficient_evidence_not_uniform() -> None:
    candidates = [candidate("a", False, 0.9, 0.8), candidate("b", False, 0.2, 0.4)]
    assert identity_weights(candidates) == {"a": 0.0, "b": 0.0}


def test_selection_weights_use_selected_identity_score() -> None:
    candidates = [candidate("a", True, 0.8, 0.9), candidate("b", True, 0.8, 0.2)]
    beta = selection_weights(candidates, {"a": 0.5, "b": 0.5}, "speaker-a", 0.0)
    assert sum(beta.values()) == pytest.approx(1.0)
    assert beta["a"] > beta["b"]
