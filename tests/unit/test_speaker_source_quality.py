"""Unit tests for WP3: Source quality assessment and multi-source fusion for speaker ID."""

from __future__ import annotations

from typing import Any

import numpy as np

from meeting_pipeline.application.speakers import SpeakerProfileInput
from meeting_pipeline.pipeline.speaker_turns import SpeakerTurn
from meeting_pipeline.speaker.clustering import GlobalSpeakerClusterer
from meeting_pipeline.speaker.source_quality import (
    SpeakerFusionPolicy,
    compute_normalized_source_weights,
    evaluate_source_quality_for_speaker_id,
    fuse_turn_candidate_scores,
    fuse_turn_speaker_embeddings,
)

MEASURED = {
    "sync_status": "reference",
    "vad_coverage": 1.0,
    "purity": 1.0,
    "valid_coverage_interval": [0.0, 4.0],
    "local_sync_residual_ms": 0.0,
    "support_duration_sec": 1.0,
}


class ControlledEncoder:
    """Mock encoder returning unit vectors mapped to speaker tag."""

    def __init__(self, dimension: int = 192) -> None:
        self.embedding_dimension = dimension
        self.calls = 0

    def encode(
        self, waveform: np.ndarray[Any, np.dtype[np.float32]]
    ) -> np.ndarray[Any, np.dtype[np.float32]]:
        self.calls += 1
        vec = np.zeros(self.embedding_dimension, dtype=np.float32)
        mean_v = float(np.mean(waveform))
        if mean_v > 0.3:
            vec[0] = 1.0
        else:
            vec[1] = 1.0
        return vec


def test_source_quality_clean_vs_noisy_and_clipping() -> None:
    """Clean audio gets high quality score; clipping and low SNR are gated out."""
    sr = 16000
    # Clean turn: 1s speech, quiet background
    full_clean = np.zeros(sr * 3, dtype=np.float32)
    t = np.arange(sr, dtype=np.float32) / sr
    full_clean[sr : sr * 2] = (0.3 * np.sin(2 * np.pi * 300 * t)).astype(np.float32)
    turn_clean = full_clean[sr : sr * 2]

    res_clean = evaluate_source_quality_for_speaker_id(
        source_id="clean_mic",
        turn_waveform=turn_clean,
        sample_rate=sr,
        full_signal=full_clean,
        turn_start_sec=1.0,
        turn_end_sec=2.0,
        **MEASURED,
    )
    assert res_clean.is_eligible
    assert res_clean.exclusion_reason is None
    assert res_clean.local_snr_proxy_db > 10.0
    assert res_clean.identity_quality_score > 0.5

    # Heavily clipped audio
    clipped_wave = np.ones(sr, dtype=np.float32)
    res_clip = evaluate_source_quality_for_speaker_id(
        source_id="clipped_mic",
        turn_waveform=clipped_wave,
        sample_rate=sr,
        **MEASURED,
    )
    assert not res_clip.is_eligible
    assert res_clip.exclusion_reason == "excessive_clipping"

    # Dropout / silent audio
    silent_wave = np.zeros(sr, dtype=np.float32)
    res_silent = evaluate_source_quality_for_speaker_id(
        source_id="silent_mic",
        turn_waveform=silent_wave,
        sample_rate=sr,
        **MEASURED,
    )
    assert not res_silent.is_eligible
    assert res_silent.exclusion_reason in (
        "insufficient_speech",
        "poor_snr",
        "inaudible_signal",
        "signal_dropout",
    )


def test_normalized_source_weights() -> None:
    """Normalized source weights sum to 1.0 and exclude disqualified sources."""
    sr = 16000
    t = np.arange(sr, dtype=np.float32) / sr
    clean = (0.3 * np.sin(2 * np.pi * 300 * t)).astype(np.float32)
    full = np.pad(clean, (sr, sr))

    q1 = evaluate_source_quality_for_speaker_id(
        "src-1", clean, sr, full_signal=full, turn_start_sec=1.0, **MEASURED
    )
    q2 = evaluate_source_quality_for_speaker_id(
        "src-2", clean * 0.5, sr, full_signal=full * 0.5, turn_start_sec=1.0, **MEASURED
    )
    q_bad = evaluate_source_quality_for_speaker_id(
        "src-bad", np.ones(sr, dtype=np.float32), sr, **MEASURED
    )

    evals = {"src-1": q1, "src-2": q2, "src-bad": q_bad}
    weights = compute_normalized_source_weights(evals)

    assert "src-bad" not in weights or weights["src-bad"] == 0.0
    assert "src-1" in weights and "src-2" in weights
    assert np.isclose(sum(weights.values()), 1.0, atol=1e-5)
    # Higher quality source gets more weight
    assert weights["src-1"] >= weights["src-2"]


def test_speaker_fusion_policies_comparison() -> None:
    """Compare P0, P1, P2, and P3 fusion policies on multi-source turn data."""
    vec_a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    vec_b = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    embs = {"src-1": vec_a, "src-2": vec_b}
    weights = {"src-1": 0.8, "src-2": 0.2}

    # P2 Embedding fusion
    fused_emb = fuse_turn_speaker_embeddings(embs, weights)
    assert fused_emb is not None
    assert np.isclose(np.linalg.norm(fused_emb), 1.0)
    assert fused_emb[0] > fused_emb[1]  # Weight 0.8 dominates

    # P3 Score fusion
    scores = {
        "src-1": {"Alice": 0.90, "Bob": 0.20},
        "src-2": {"Alice": 0.60, "Bob": 0.50},
    }
    fused_scores = fuse_turn_candidate_scores(scores, weights)
    # Alice: 0.9*0.8 + 0.6*0.2 = 0.72 + 0.12 = 0.84
    assert np.isclose(fused_scores["Alice"], 0.84, atol=1e-4)
    # Bob: 0.2*0.8 + 0.5*0.2 = 0.16 + 0.10 = 0.26
    assert np.isclose(fused_scores["Bob"], 0.26, atol=1e-4)


def test_global_clusterer_with_quality_gating() -> None:
    """GlobalSpeakerClusterer excludes clipped/dropout phone and relies on clean phone."""
    sr = 16000
    encoder = ControlledEncoder(dimension=192)
    clusterer = GlobalSpeakerClusterer(
        encoder=encoder,
        fusion_policy=SpeakerFusionPolicy.P2_EMBEDDING_FUSION,
        min_seed_duration_sec=0.5,
    )

    t = np.arange(int(sr * 1.5), dtype=np.float32) / sr
    good_signal = np.zeros(sr * 4, dtype=np.float32)
    good_signal[sr : sr + len(t)] = 0.6  # Speaker tag > 0.3, not clipped

    # Phone B has heavy clipping during the turn
    bad_signal = np.zeros(sr * 4, dtype=np.float32)
    bad_signal[sr : sr + len(t)] = 1.0  # Clipped to 1.0

    aligned = {"phone_clean": good_signal, "phone_clipped": bad_signal}
    turn = SpeakerTurn(
        turn_id="turn-1",
        start_sec=1.0,
        end_sec=2.5,
        speech_region_id="reg-1",
        track_id="tr-1",
        speaker_count=1,
        source_activity={
            sid: {
                "speech_coverage": 1.0,
                "local_speaker_purity": 1.0,
                "support_duration_sec": 1.5,
                "speech_intervals": [[1.0, 2.5]],
            }
            for sid in aligned
        },
    )

    assignments, _decisions, _summary = clusterer.cluster_and_identify(
        turns=[turn],
        aligned_signals=aligned,
        sample_rate=sr,
        profiles=[],
        sync_metadata={
            sid: {
                "status": "reference" if sid == "phone_clean" else "aligned",
                "residual_ms": 0.0,
                "valid_coverage_interval": [0.0, 4.0],
            }
            for sid in aligned
        },
    )

    assign = assignments["turn-1"]
    assert len(assign.source_evidence) == 2
    ev_by_src = {e["source_id"]: e for e in assign.source_evidence}
    assert ev_by_src["phone_clean"]["is_eligible"] is True
    assert ev_by_src["phone_clipped"]["is_eligible"] is False
    assert ev_by_src["phone_clipped"]["exclusion_reason"] == "excessive_clipping"
    assert ev_by_src["phone_clean"]["identity_weight"] == 1.0


def test_invalid_source_evidence_never_gets_weight() -> None:
    signal = np.full(16000, 0.5, dtype=np.float32)
    cases = [
        ({"sync_status": "alignment_failed"}, "alignment_failed"),
        (
            {"sync_status": "drift_unresolved", "local_sync_residual_ms": None},
            "drift_unresolved_without_local_evidence",
        ),
        ({"coverage_fraction": 0.2}, "outside_valid_coverage"),
        ({"support_duration_sec": 0.0, "vad_coverage": 0.0}, "no_source_speech_support"),
        ({"purity": 0.5}, "multiple_local_speakers"),
    ]
    for overrides, reason in cases:
        result = evaluate_source_quality_for_speaker_id(
            "loud_but_invalid", signal, 16000, **{**MEASURED, **overrides}
        )
        assert result.exclusion_reason == reason
        assert result.identity_weight == 0.0
        assert compute_normalized_source_weights({"bad": result}) == {}
    missing = evaluate_source_quality_for_speaker_id("unmeasured", signal, 16000)
    assert missing.speech_coverage is None
    assert missing.local_speaker_purity is None
    assert missing.local_snr_proxy_db is None


def test_active_crop_speech_is_not_discounted_twice() -> None:
    sr = 16000
    time = np.arange(round(sr * 0.3), dtype=np.float32) / sr
    clip = (0.3 * np.sin(2 * np.pi * 220 * time)).astype(np.float32)
    full = np.pad(clip, (sr, sr))
    result = evaluate_source_quality_for_speaker_id(
        "short_support", clip, sr, full_signal=full,
        turn_start_sec=1.0, turn_end_sec=1.3,
        **{**MEASURED, "vad_coverage": 0.2, "support_duration_sec": 0.4},
    )
    assert result.speech_seconds == 0.3
    assert result.is_eligible


def test_all_sources_invalid_does_not_encode_or_create_unknown() -> None:
    encoder = ControlledEncoder()
    clusterer = GlobalSpeakerClusterer(encoder, min_seed_duration_sec=0.5)
    turn = SpeakerTurn(
        turn_id="t",
        speech_region_id="r",
        start_sec=0.0,
        end_sec=1.0,
        track_id="local-1",
        speaker_count=1,
        source_activity={
            sid: {
                "speech_coverage": 1.0,
                "local_speaker_purity": 1.0,
                "support_duration_sec": 1.0,
                "speech_intervals": [[0.0, 1.0]],
            }
            for sid in ("failed", "short")
        },
    )
    assignments, _, summary = clusterer.cluster_and_identify(
        [turn],
        {
            "failed": np.full(16000, 0.5, dtype=np.float32),
            "short": np.full(16000, 0.5, dtype=np.float32),
        },
        16000,
        [],
        sync_metadata={
            "failed": {"status": "alignment_failed", "valid_coverage_interval": [0.0, 1.0]},
            "short": {"status": "aligned", "valid_coverage_interval": [0.0, 0.1]},
        },
    )
    assert encoder.calls == 0
    assert summary["total_clusters"] == 0
    assert assignments["t"].speaker_status == "ambiguous"
    assert all(row["identity_weight"] == 0.0 for row in assignments["t"].source_evidence)


def test_p3_real_path_preserves_conflicting_source_scores(monkeypatch) -> None:
    sr = 16000
    a = np.zeros(sr * 3, dtype=np.float32)
    b = np.zeros(sr * 3, dtype=np.float32)
    a[sr : 2 * sr] = 0.6
    b[sr : 2 * sr] = 0.2
    turn = SpeakerTurn(
        turn_id="t",
        speech_region_id="r",
        start_sec=1.0,
        end_sec=2.0,
        track_id="local-1",
        speaker_count=1,
        source_activity={
            sid: {
                "speech_coverage": 1.0,
                "local_speaker_purity": 1.0,
                "support_duration_sec": 1.0,
                "speech_intervals": [[1.0, 2.0]],
            }
            for sid in ("a", "b")
        },
    )
    sync = {
        sid: {
            "status": "reference" if sid == "a" else "aligned",
            "residual_ms": 0.0,
            "valid_coverage_interval": [0.0, 3.0],
        }
        for sid in ("a", "b")
    }
    profiles = [
        SpeakerProfileInput("alice", "Alice", np.eye(192, dtype=np.float32)[0]),
        SpeakerProfileInput("bob", "Bob", np.eye(192, dtype=np.float32)[1]),
    ]
    clusterer = GlobalSpeakerClusterer(
        ControlledEncoder(),
        fusion_policy=SpeakerFusionPolicy.P3_WEIGHTED_SCORE_FUSION,
        min_seed_duration_sec=0.5,
    )
    result, clusters, _ = clusterer.cluster_and_identify(
        [turn], {"a": a, "b": b}, sr, profiles, sync_metadata=sync
    )
    assert result["t"].speaker_status == "ambiguous"
    assert result["t"].needs_review
    assert "source_disagreement" in result["t"].decision_reason
    assert result["t"].meeting_speaker_id == clusters[0].meeting_speaker_id
    evidence = {row["source_id"]: row for row in result["t"].source_evidence}
    assert evidence["a"]["candidate_cosine_scores"]["alice"] == 1.0
    assert evidence["b"]["candidate_cosine_scores"]["bob"] == 1.0

    # The same turn is the only observation, even though two phones recorded it.
    agreement, _, _ = clusterer.cluster_and_identify(
        [turn], {"a": a, "b": a * 0.8}, sr, profiles, sync_metadata=sync
    )
    assert agreement["t"].speaker_id == "alice"
    assert "source_disagreement" not in agreement["t"].decision_reason

    import meeting_pipeline.speaker.clustering as clustering_module

    original = clustering_module.evaluate_source_quality_for_speaker_id

    def weighted_quality(**kwargs):
        result = original(**kwargs)
        if result.is_eligible:
            result.identity_quality_score = 0.9 if kwargs["source_id"] == "a" else 0.35
        return result

    monkeypatch.setattr(
        clustering_module, "evaluate_source_quality_for_speaker_id", weighted_quality
    )
    dominant, _, _ = clusterer.cluster_and_identify(
        [turn], {"a": a, "b": b}, sr, profiles, sync_metadata=sync
    )
    assert dominant["t"].speaker_id == "alice"
    assert "dominant_source_top1:a" in dominant["t"].decision_reason
    monkeypatch.setattr(clustering_module, "evaluate_source_quality_for_speaker_id", original)

    # An excluded phone cannot vote, and P3 then makes the sole valid comparison.
    sync["b"]["status"] = "alignment_failed"
    accepted, _, _ = clusterer.cluster_and_identify(
        [turn], {"a": a, "b": b}, sr, profiles, sync_metadata=sync
    )
    assert accepted["t"].speaker_id == "alice"
    assert (
        next(row for row in accepted["t"].source_evidence if row["source_id"] == "b")[
            "identity_weight"
        ]
        == 0.0
    )
    unknown, _, _ = clusterer.cluster_and_identify(
        [turn], {"a": a, "b": b}, sr, [], sync_metadata=sync
    )
    assert unknown["t"].speaker_status == "unknown"
    partial, _, _ = clusterer.cluster_and_identify(
        [turn], {"a": a, "b": b}, sr, profiles[:1], sync_metadata=sync
    )
    assert partial["t"].speaker_id == "alice"
