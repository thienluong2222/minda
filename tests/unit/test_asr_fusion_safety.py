"""Guard fusion against rejected ASR and uncalibrated single-source scores."""

import numpy as np

from meeting_pipeline.domain.contracts import MeetingSegment, SourceHypothesis
from meeting_pipeline.fusion.confusion_network import build_confusion_network
from meeting_pipeline.fusion.provenance import build_final_timeline_item


def test_rejected_asr_cannot_vote_in_confusion_network() -> None:
    valid = SourceHypothesis(
        meeting_id="meeting",
        segment_id="segment",
        source_id="phone-a",
        text="xin chào",
        transcript_quality_score=0.6,
    )
    rejected = SourceHypothesis(
        meeting_id="meeting",
        segment_id="segment",
        source_id="phone-b",
        text="a " * 100,
        asr_status="unreliable",
        transcript_quality_score=1.0,
    )

    bins = build_confusion_network({"phone-a": valid, "phone-b": rejected})

    assert [b.candidates for b in bins] == [
        {"phone-a": "xin"},
        {"phone-a": "chào"},
    ]
    assert build_confusion_network({"phone-b": rejected}) == []


def test_one_source_does_not_claim_calibrated_confidence() -> None:
    segment = MeetingSegment(
        meeting_id="meeting",
        segment_id="segment",
        start_sec=0.0,
        end_sec=1.0,
    )
    hypothesis = SourceHypothesis(
        meeting_id="meeting",
        segment_id="segment",
        source_id="phone-a",
        text="xin",
        transcript_quality_score=0.7,
    )

    result = build_final_timeline_item(
        meeting_id="meeting",
        segment=segment,
        fused_text="xin",
        word_decisions=[
            {
                "word": "xin",
                "confidence": 1.0,
                "supporting_sources": ["phone-a"],
                "representative_source_id": "phone-a",
            }
        ],
        speaker_id="speaker-a",
        speaker_confidence=0.8,
        source_hypotheses={"phone-a": hypothesis},
        aligned_audio_signals={"phone-a": np.zeros(16000, dtype=np.float32)},
    )

    assert result.transcript_confidence is None
    assert result.word_provenance[0].confidence is None
