"""Unit tests for WP5: Transcript fusion, Abstain vs Epsilon, and Provenance."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from meeting_pipeline.domain.contracts import (
    MeetingSegment,
    SourceHypothesis,
    WordHypothesis,
)
from meeting_pipeline.fusion.alignment import ABSTAIN_TOKEN, EPSILON_TOKEN
from meeting_pipeline.fusion.baselines import (
    fuse_f3_rover,
    fuse_f4_asr_weighted,
    fuse_f5_rule_weighted,
    fuse_f5_rule_weighted_corrected,
)
from meeting_pipeline.fusion.confusion_network import ConfusionBin, build_confusion_network
from meeting_pipeline.fusion.provenance import build_final_timeline_item


def test_confusion_network_distinguishes_abstain_from_epsilon() -> None:
    """An un-run source must be excluded from voting, while empty transcribed gets EPSILON."""
    hyp_a = SourceHypothesis(
        meeting_id="m1",
        segment_id="s1",
        source_id="src_a",
        text="xin chào các bạn",
        asr_status="transcribed",
        audio_quality_score=0.9,
        transcript_quality_score=0.85,
        words=[
            WordHypothesis(word="xin", start_sec=0.1, end_sec=0.4, asr_confidence=0.9),
            WordHypothesis(word="chào", start_sec=0.4, end_sec=0.7, asr_confidence=0.9),
            WordHypothesis(word="các", start_sec=0.7, end_sec=0.9, asr_confidence=0.9),
            WordHypothesis(word="bạn", start_sec=0.9, end_sec=1.2, asr_confidence=0.9),
        ],
    )
    # Source B was not run (e.g. pruned by adaptive ASR)
    hyp_b = SourceHypothesis(
        meeting_id="m1",
        segment_id="s1",
        source_id="src_b",
        text="",
        asr_status="not_run",
        audio_quality_score=0.4,
        transcript_quality_score=0.0,
    )
    # Source C was transcribed but heard silence
    hyp_c = SourceHypothesis(
        meeting_id="m1",
        segment_id="s1",
        source_id="src_c",
        text="",
        asr_status="transcribed",
        audio_quality_score=0.7,
        transcript_quality_score=0.5,
    )

    hypotheses = {"src_a": hyp_a, "src_b": hyp_b, "src_c": hyp_c}
    bins = build_confusion_network(hypotheses)

    assert len(bins) == 4
    for b in bins:
        assert b.candidates["src_a"] in ["xin", "chào", "các", "bạn"]
        # src_b was not run, so it must be excluded from the voting pool (abstain)
        assert "src_b" not in b.candidates
        # src_c was transcribed (silent), so it casts an EPSILON vote
        assert b.candidates["src_c"] == EPSILON_TOKEN
        assert b.source_scores["src_c"] == 0.5


def test_abstain_source_does_not_delete_words() -> None:
    """An abstained source should not act as a deletion vote in F3, F4, F5."""
    bin1 = ConfusionBin(
        bin_idx=0,
        candidates={"src_a": "xin", "src_b": ABSTAIN_TOKEN},
        confidences={"src_a": 0.8, "src_b": 0.0},
        source_scores={"src_a": 0.9, "src_b": 0.0},
    )
    bin2 = ConfusionBin(
        bin_idx=1,
        candidates={"src_a": "chào", "src_b": ABSTAIN_TOKEN},
        confidences={"src_a": 0.8, "src_b": 0.0},
        source_scores={"src_a": 0.9, "src_b": 0.0},
    )
    bins = [bin1, bin2]

    f3_text, _ = fuse_f3_rover(bins)
    assert f3_text == "xin chào"

    f4_text, _ = fuse_f4_asr_weighted(bins)
    assert f4_text == "xin chào"

    f5_text, _ = fuse_f5_rule_weighted(bins)
    assert f5_text == "xin chào"

    f5_corr_text, _ = fuse_f5_rule_weighted_corrected(bins)
    assert f5_corr_text == "xin chào"


def test_f5_corrected_protects_best_source_from_secondary_hallucination() -> None:
    """When best source is silent (EPSILON), weak secondary hallucination is rejected."""
    # Best source (src_a) heard nothing: EPSILON with score 0.8, conf 0.2 -> w = 0.64
    # Secondary source (src_b) heard 'ảo_giác': word with score 0.6, conf 0.6 -> w = 0.36
    # cand_vote (0.36) < best_vote (0.64) -> margin negative -> rejected!
    bin_hallucination = ConfusionBin(
        bin_idx=0,
        candidates={"src_a": EPSILON_TOKEN, "src_b": "ảo_giác"},
        confidences={"src_a": 0.2, "src_b": 0.6},
        source_scores={"src_a": 0.8, "src_b": 0.6},
    )

    text, _ = fuse_f5_rule_weighted_corrected(
        [bin_hallucination],
        source_hypotheses={
            "src_a": SourceHypothesis(
                meeting_id="m",
                segment_id="s",
                source_id="src_a",
                text="",
                transcript_quality_score=0.8,
            ),
            "src_b": SourceHypothesis(
                meeting_id="m",
                segment_id="s",
                source_id="src_b",
                text="ảo_giác",
                transcript_quality_score=0.6,
            ),
        },
    )
    assert text == ""


def test_f5_corrected_requires_consensus_to_delete_best_source_word() -> None:
    """Best source word is preserved if only 1 secondary source votes to delete it."""
    # src_a (best): "quan_trọng", w = 0.8 * 0.9 = 0.72
    # src_b: EPSILON, w = 0.6 * (1.0 - 0.1) = 0.54
    # 1 source cannot delete best source word without consensus of >= 2
    bin_important = ConfusionBin(
        bin_idx=0,
        candidates={"src_a": "quan_trọng", "src_b": EPSILON_TOKEN},
        confidences={"src_a": 0.9, "src_b": 0.1},
        source_scores={"src_a": 0.7, "src_b": 0.8},
    )

    text, decisions = fuse_f5_rule_weighted_corrected(
        [bin_important],
        source_hypotheses={
            "src_a": SourceHypothesis(
                meeting_id="m",
                segment_id="s",
                source_id="src_a",
                text="quan_trọng",
                transcript_quality_score=0.9,
            ),
            "src_b": SourceHypothesis(
                meeting_id="m",
                segment_id="s",
                source_id="src_b",
                text="",
                transcript_quality_score=0.5,
            ),
        },
    )
    assert text == "quan_trọng"
    assert len(decisions) == 1
    assert decisions[0]["word"] == "quan_trọng"
    assert decisions[0]["representative_source_id"] == "src_a"


def test_word_provenance_and_evidence_clips_roundtrip(tmp_path: Path) -> None:
    """Verify build_final_timeline_item creates WordProvenance and writes clips."""
    meeting_id = "test_meeting_01"
    seg = MeetingSegment(
        meeting_id=meeting_id,
        segment_id="turn_001",
        start_sec=0.0,
        end_sec=1.0,
    )
    word_decisions = [
        {
            "word": "bắt",
            "confidence": 0.95,
            "supporting_sources": ["mic1", "mic2"],
            "representative_source_id": "mic1",
            "needs_review": False,
        },
        {
            "word": "đầu",
            "confidence": 0.72,
            "supporting_sources": ["mic1"],
            "representative_source_id": "mic1",
            "needs_review": True,
        },
    ]
    hypotheses = {
        "mic1": SourceHypothesis(
            meeting_id=meeting_id,
            segment_id="turn_001",
            source_id="mic1",
            text="bắt đầu",
            transcript_quality_score=0.9,
        ),
        "mic2": SourceHypothesis(
            meeting_id=meeting_id,
            segment_id="turn_001",
            source_id="mic2",
            text="bắt",
            transcript_quality_score=0.8,
        ),
    }
    audio_signals = {
        "mic1": np.zeros(16000, dtype=np.float32),
        "mic2": np.zeros(16000, dtype=np.float32),
    }

    clips_dir = tmp_path / "evidence_clips"
    timeline_item = build_final_timeline_item(
        meeting_id=meeting_id,
        segment=seg,
        fused_text="bắt đầu",
        word_decisions=word_decisions,
        speaker_id="speaker_01",
        speaker_confidence=0.88,
        source_hypotheses=hypotheses,
        aligned_audio_signals=audio_signals,
        output_clips_dir=clips_dir,
        sample_rate=16000,
    )

    assert timeline_item.text == "bắt đầu"
    assert timeline_item.primary_source_id == "mic1"
    assert len(timeline_item.word_provenance) == 2
    assert timeline_item.word_provenance[0].output_word == "bắt"
    assert timeline_item.word_provenance[0].needs_review is False
    assert timeline_item.word_provenance[1].output_word == "đầu"
    assert timeline_item.word_provenance[1].needs_review is True

    # Check evidence clips written
    assert "mic1" in timeline_item.evidence_clips
    assert "mic2" in timeline_item.evidence_clips
