"""Unit tests for transcript fusion F0-F6 and provenance tracking (Milestone 6)."""

from pathlib import Path

import numpy as np

from meeting_pipeline.domain.contracts import MeetingSegment, SourceHypothesis, WordHypothesis
from meeting_pipeline.fusion.alignment import EPSILON_TOKEN, align_word_sequences
from meeting_pipeline.fusion.baselines import (
    fuse_f0_fixed,
    fuse_f1_best_segment,
    fuse_f2_oracle_best,
    fuse_f3_rover,
    fuse_f4_asr_weighted,
    fuse_f5_rule_weighted,
    fuse_f6_learned,
)
from meeting_pipeline.fusion.confusion_network import build_confusion_network
from meeting_pipeline.fusion.model import LearnedFusionModel
from meeting_pipeline.fusion.provenance import build_final_timeline_item


def test_align_word_sequences() -> None:
    # Exact match
    seq1 = ["tôi", "đi", "học"]
    seq2 = ["tôi", "đi", "học"]
    a1, a2 = align_word_sequences(seq1, seq2)
    assert a1 == seq1
    assert a2 == seq2

    # Substitution
    seq_sub = ["tôi", "muốn", "học"]
    a1, a2 = align_word_sequences(seq1, seq_sub)
    assert len(a1) == len(a2) == 3

    # Insertion / Deletion
    seq_short = ["tôi", "học"]
    a1, a2 = align_word_sequences(seq1, seq_short)
    assert len(a1) == len(a2) == 3
    assert EPSILON_TOKEN in a2


def test_confusion_network_construction() -> None:
    h1 = SourceHypothesis(
        meeting_id="m1",
        segment_id="s1",
        source_id="d1",
        text="xin chào các bạn",
        words=[
            WordHypothesis(word="xin", start_sec=0.1, end_sec=0.3, asr_confidence=0.9),
            WordHypothesis(word="chào", start_sec=0.3, end_sec=0.5, asr_confidence=0.9),
            WordHypothesis(word="các", start_sec=0.5, end_sec=0.7, asr_confidence=0.85),
            WordHypothesis(word="bạn", start_sec=0.7, end_sec=0.9, asr_confidence=0.88),
        ],
        transcript_quality_score=0.9,
    )
    h2 = SourceHypothesis(
        meeting_id="m1",
        segment_id="s1",
        source_id="d2",
        text="xin chào bạn",
        words=[
            WordHypothesis(word="xin", start_sec=0.1, end_sec=0.3, asr_confidence=0.8),
            WordHypothesis(word="chào", start_sec=0.3, end_sec=0.5, asr_confidence=0.8),
            WordHypothesis(word="bạn", start_sec=0.5, end_sec=0.8, asr_confidence=0.85),
        ],
        transcript_quality_score=0.7,
    )

    hyps = {"d1": h1, "d2": h2}
    bins = build_confusion_network(hyps, backbone_source_id="d1")
    assert len(bins) == 4
    assert bins[0].candidates["d1"] == "xin"
    assert bins[0].candidates["d2"] == "xin"
    assert bins[2].candidates["d1"] == "các"
    assert bins[2].candidates["d2"] == EPSILON_TOKEN


def test_all_fusion_baselines_f0_to_f6() -> None:
    h1 = SourceHypothesis(
        meeting_id="m1",
        segment_id="s1",
        source_id="d1",
        text="tôi đi học",
        transcript_quality_score=0.85,
    )
    h2 = SourceHypothesis(
        meeting_id="m1",
        segment_id="s1",
        source_id="d2",
        text="tôi đi làm",
        transcript_quality_score=0.60,
    )
    h3 = SourceHypothesis(
        meeting_id="m1",
        segment_id="s1",
        source_id="d3",
        text="tôi đi học",
        transcript_quality_score=0.80,
    )

    hyps = {"d1": h1, "d2": h2, "d3": h3}
    bins = build_confusion_network(hyps)

    # F0_FIXED
    t0, _ = fuse_f0_fixed(hyps, fixed_source_id="d1")
    assert t0 == "tôi đi học"

    # F1_BEST_SEGMENT
    t1, _ = fuse_f1_best_segment(hyps)
    assert t1 == "tôi đi học"

    # F2_ORACLE_BEST
    t2, _ = fuse_f2_oracle_best(hyps, reference_text="tôi đi làm")
    assert t2 == "tôi đi làm"

    # F3_ROVER
    t3, _ = fuse_f3_rover(bins)
    assert t3 == "tôi đi học"  # 2 votes for học vs 1 for làm

    # F4_ASR_WEIGHTED
    t4, _ = fuse_f4_asr_weighted(bins)
    assert len(t4.split()) == 3

    # F5_RULE_WEIGHTED
    t5, _ = fuse_f5_rule_weighted(bins)
    assert t5 == "tôi đi học"

    # F6_LEARNED
    learned_model = LearnedFusionModel()
    t6, _ = fuse_f6_learned(bins, learned_model)
    assert len(t6.split()) == 3


def test_fusion_suppresses_single_source_repetition_hallucination() -> None:
    clean = SourceHypothesis(
        meeting_id="m1",
        segment_id="s1",
        source_id="phone-clean",
        text="mấy ngày đầu thúy hà",
        asr_features={"mean_confidence": 0.9},
        transcript_quality_score=0.9,
    )
    hallucinated = SourceHypothesis(
        meeting_id="m1",
        segment_id="s1",
        source_id="phone-hallucinated",
        text="mấy ngày đầu thúy hà tài liệu tài liệu tài liệu tài liệu",
        asr_features={"mean_confidence": 0.85},
        transcript_quality_score=0.3,
    )
    hypotheses = {
        clean.source_id: clean,
        hallucinated.source_id: hallucinated,
    }
    bins = build_confusion_network(hypotheses)

    rover_text, _ = fuse_f3_rover(bins)
    asr_weighted_text, _ = fuse_f4_asr_weighted(bins)
    rule_weighted_text, _ = fuse_f5_rule_weighted(bins)
    learned_text, _ = fuse_f6_learned(bins, LearnedFusionModel())

    expected = "mấy ngày đầu thúy hà"
    assert rover_text == expected
    assert asr_weighted_text == expected
    assert rule_weighted_text == expected
    assert learned_text == expected


def test_build_final_timeline_item_provenance(tmp_path: Path) -> None:
    seg = MeetingSegment(
        schema_version="1.0",
        meeting_id="m1",
        segment_id="s1",
        start_sec=0.5,
        end_sec=2.0,
    )
    h1 = SourceHypothesis(
        meeting_id="m1",
        segment_id="s1",
        source_id="d1",
        text="xin chào",
        transcript_quality_score=0.9,
    )
    decisions = [
        {
            "word": "xin",
            "confidence": 0.95,
            "supporting_sources": ["d1"],
            "representative_source_id": "d1",
        },
        {
            "word": "chào",
            "confidence": 0.92,
            "supporting_sources": ["d1"],
            "representative_source_id": "d1",
        },
    ]

    audio_sigs = {
        "d1": np.ones(32000, dtype=np.float32) * 0.1,
    }

    item = build_final_timeline_item(
        meeting_id="m1",
        segment=seg,
        fused_text="xin chào",
        word_decisions=decisions,
        speaker_id="spk_01",
        speaker_confidence=0.94,
        source_hypotheses={"d1": h1},
        aligned_audio_signals=audio_sigs,
        output_clips_dir=tmp_path / "clips",
    )

    assert item.primary_source_id == "d1"
    assert len(item.word_provenance) == 2
    assert "d1" in item.evidence_clips
    clip_file = Path(item.evidence_clips["d1"])
    assert clip_file.exists()
