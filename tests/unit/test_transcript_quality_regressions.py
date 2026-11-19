"""Regression cases for real meeting cuts, verification and cache correctness."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

from meeting_backend.modules.transcripts.service import review_context, view_row
from meeting_pipeline.adapters.phowhisper_asr import AsrResult, BaseAsrAdapter
from meeting_pipeline.asr.cache import AsrCache
from meeting_pipeline.asr.segment_asr import transcribe_turn_adaptive
from meeting_pipeline.audio.coverage import covers
from meeting_pipeline.audio.timeline_alignment import ClockSpan
from meeting_pipeline.config import AsrConfig, load_config
from meeting_pipeline.domain.contracts import SourceHypothesis, WordHypothesis
from meeting_pipeline.domain.transcription import TimedWord
from meeting_pipeline.fusion.baselines import fuse_f5_rule_weighted_corrected
from meeting_pipeline.fusion.confusion_network import build_confusion_network
from meeting_pipeline.pipeline.speaker_turns import SpeakerTurn
from meeting_pipeline.pipeline.stages.safe_merge import safe_merge_speaker_turns
from meeting_pipeline.pipeline.timeline_audio import TimelineAudioPipeline
from meeting_pipeline.speaker.clustering import TurnAssignment


class SequenceAsr(BaseAsrAdapter):
    def __init__(self, texts):
        self.texts = iter(texts)
        self.calls = 0

    def transcribe(self, waveform, sample_rate=16000):
        self.calls += 1
        text = next(self.texts)
        if text is None:
            return AsrResult(text="", words=[], status="unreliable", warnings=["repeated_word"])
        return AsrResult(
            text=text,
            words=[
                TimedWord(text=word, start_sec=0.05 + i * 0.05, end_sec=0.1 + i * 0.05)
                for i, word in enumerate(text.split())
            ],
            status="transcribed",
        )


@pytest.mark.parametrize("seam", [0.4, 1.1, 1.7])
@pytest.mark.parametrize("same_recording", [True, False])
def test_alignment_knots_are_soft_but_recording_edges_remain_hard(tmp_path, seam, same_recording):
    config = load_config(Path("configs/default.yaml"))
    pipeline = TimelineAudioPipeline(config)
    sr = pipeline.sample_rate
    audio = tmp_path / "capture.wav"
    sf.write(audio, np.full(sr * 2, 0.1, dtype=np.float32), sr)
    second = "a" if same_recording else "b"
    spans = [
        ClockSpan("a", "meeting", 0, seam, 1, 0, "extrapolated"),
        ClockSpan(second, "meeting", seam, 2, 1, 0, "acoustic", residual_ms=10),
    ]
    _, sync, boundaries, _ = pipeline._render(
        tmp_path,
        1,
        spans,
        {key: {"asset_id": "asset", "source_in_ms": 0} for key in {"a", second}},
        {"a": "mic", second: "mic"},
        {"asset": {"path": audio}},
        0,
        2,
    )
    assert set(boundaries) == ({0, 2} if same_recording else {0, seam, 2})
    assert covers(sync["source-1"], 0, 2)
    assert len(sync["source-1"]["segments"]) == 2  # Keep alignment audit intact.


@pytest.mark.parametrize("gap", [0, 0.001, 0.1])
def test_coverage_joins_only_contiguous_recorded_spans(gap):
    metadata = {"valid_coverage_intervals": [[0, 1], [1 + gap, 3]]}
    assert covers(metadata, 0.5, 2) is (gap == 0)
    assert covers(metadata, 1 + gap, 2)


def _speaker(turn_id, start, end):
    return SpeakerTurn(
        turn_id=turn_id,
        start_sec=start,
        end_sec=end,
        speech_region_id="speech",
        track_id="local",
        speaker_count=1,
    )


def _identity(turn_id):
    return TurnAssignment(
        turn_id=turn_id,
        cluster_id="person",
        meeting_speaker_id="person",
        speaker_id=None,
        speaker_label="Người lạ 1",
        speaker_status="unknown",
        decision_reason="test",
        needs_review=False,
    )


@pytest.mark.parametrize("boundary", [None, 1, 1.05])
def test_safe_merging_never_bridges_recording_or_pause_boundaries(boundary):
    turns = [_speaker("a", 0, 1), _speaker("b", 1.1, 2)]
    result = safe_merge_speaker_turns(
        turns,
        {t.turn_id: _identity(t.turn_id) for t in turns},
        hard_boundaries=[] if boundary is None else [boundary],
    )
    assert len(result) == (1 if boundary is None else 2)
    assert sum(len(t.sub_turn_ids) for t in result) == 2


@pytest.mark.parametrize(
    "change",
    [
        {"language": "en"},
        {"max_new_tokens": 128},
        {"max_decode_attempts": 1},
        {"max_words_per_second": 5},
    ],
)
def test_changed_decoding_or_acceptance_rules_do_not_reuse_stale_asr(tmp_path, change):
    config = AsrConfig(model_id="model", model_revision="pinned")
    adapter = SequenceAsr(["xin chào", "đã cập nhật"])
    audio = {"mic": np.full(32000, 0.1, dtype=np.float32)}
    cache = AsrCache(tmp_path / "cache")
    args = dict(
        meeting_id="m",
        turn_id="t",
        core_start_sec=0,
        core_end_sec=2,
        aligned_signals=audio,
        sync_metadata={},
        asr_adapter=adapter,
        cache=cache,
    )
    first, _ = transcribe_turn_adaptive(**args, asr_config=config)
    cached, _ = transcribe_turn_adaptive(**args, asr_config=config)
    assert adapter.calls == 1 and first["mic"].text == cached["mic"].text
    changed, _ = transcribe_turn_adaptive(**args, asr_config=config.model_copy(update=change))
    assert adapter.calls == 2 and changed["mic"].text == "đã cập nhật"


@pytest.mark.parametrize(
    "texts", [[None, "không đồng ý", "không đồng ý"], ["đồng ý", "không đồng ý", "không đồng ý"]]
)
def test_verification_reaches_third_clean_source_after_rejection_or_disagreement(texts):
    adapter = SequenceAsr(texts)
    hypotheses, metadata = transcribe_turn_adaptive(
        "m",
        "t",
        0,
        2,
        {f"mic-{i}": np.full(32000, 0.1, dtype=np.float32) for i in range(3)},
        {},
        adapter,
        AsrConfig(model_id="model", model_revision="pinned"),
    )
    assert adapter.calls == 3
    assert len(metadata["scheduled_sources"]) == 3
    assert sum(h.asr_status == "transcribed" for h in hypotheses.values()) >= 2
    assert any("scheduled_verification" in h.routing_reason for h in hypotheses.values())


def test_missing_model_confidence_is_verified_and_identical_text_needs_no_third_decode():
    adapter = SequenceAsr(["đồng ý", "đồng ý"])
    _, metadata = transcribe_turn_adaptive(
        "m",
        "t",
        0,
        2,
        {f"mic-{i}": np.full(32000, 0.1, dtype=np.float32) for i in range(3)},
        {},
        adapter,
        AsrConfig(model_id="model", model_revision="pinned"),
    )
    assert adapter.calls == 2
    assert len(metadata["abstained_sources"]) == 1


def test_verification_respects_explicit_resource_limit():
    adapter = SequenceAsr(["đồng ý"])
    _, metadata = transcribe_turn_adaptive(
        "m",
        "t",
        0,
        2,
        {f"mic-{i}": np.full(32000, 0.1, dtype=np.float32) for i in range(3)},
        {},
        adapter,
        AsrConfig(model_id="model", model_revision="pinned", max_verification_sources=1),
    )
    assert adapter.calls == 1 and len(metadata["scheduled_sources"]) == 1


def test_short_negative_answer_is_kept_but_requires_review():
    adapter = SequenceAsr(["không"])
    hypotheses, _ = transcribe_turn_adaptive(
        "m",
        "short",
        0,
        0.3,
        {"mic": np.full(4800, 0.1, dtype=np.float32)},
        {},
        adapter,
        AsrConfig(model_id="model", model_revision="pinned"),
    )
    assert hypotheses["mic"].text == "không"
    assert "asr_short_context" in hypotheses["mic"].asr_warnings
    assert "asr_single_source_unverified" in hypotheses["mic"].asr_warnings


@pytest.mark.parametrize("texts,valid", [(["không", "không"], 2), (["được lên", None, None], 0)])
def test_short_answers_need_review_when_actual_other_sources_reject_them(texts, valid):
    adapter = SequenceAsr(texts)
    hypotheses, _ = transcribe_turn_adaptive(
        "m",
        "short",
        0,
        0.3,
        {f"mic-{i}": np.full(4800, 0.1, dtype=np.float32) for i in range(3)},
        {},
        adapter,
        AsrConfig(model_id="model", model_revision="pinned"),
    )
    assert sum(h.asr_status == "transcribed" for h in hypotheses.values()) == valid
    if valid == 0:
        candidate = next(h for h in hypotheses.values() if h.text)
        assert "asr_unverified_short_fragment" in candidate.asr_warnings
        assert candidate.text == "được lên"  # Auditable, never part of the accepted transcript.


@pytest.mark.parametrize("other", ["đồng ý", "không đồng ý", None])
def test_primary_winning_does_not_hide_disagreement_or_single_source(other):
    primary = SourceHypothesis(
        meeting_id="m",
        segment_id="t",
        source_id="a",
        text="đồng ý",
        words=[
            WordHypothesis(word=w, start_sec=i, end_sec=i + 0.5)
            for i, w in enumerate(["đồng", "ý"])
        ],
        asr_status="transcribed",
        transcript_quality_score=0.9,
    )
    hypotheses = {"a": primary}
    if other is not None:
        hypotheses["b"] = primary.model_copy(
            update={
                "source_id": "b",
                "text": other,
                "transcript_quality_score": 0.2,
                "words": [
                    WordHypothesis(word=w, start_sec=i, end_sec=i + 0.5)
                    for i, w in enumerate(other.split())
                ],
            }
        )
    text, decisions = fuse_f5_rule_weighted_corrected(
        build_confusion_network(hypotheses), hypotheses
    )
    assert text == "đồng ý"
    assert any(d["needs_review"] for d in decisions) is (other != "đồng ý")


def test_review_explanations_survive_old_versions_without_exposing_internal_data():
    row = {
        "_id": "row",
        "needs_review": True,
        "data": {
            "warnings": ["unverified_fusion_consensus", "asr_exception: /private/internal/file"],
            "source_evidence": [{"asr_warnings": ["asr_short_context"]}],
        },
    }
    view = view_row(row)
    assert "data" not in view and len(view["review_reasons"]) == 2
    assert any("ngắn" in reason for reason in view["review_reasons"])
    assert not any("/private" in reason for reason in view["review_reasons"])
    assert view_row({"_id": "legacy"})["review_reasons"] == []


def test_single_source_review_does_not_claim_that_other_recordings_disagree():
    view = view_row(
        {
            "_id": "single",
            "data": {
                "warnings": [
                    "asr_single_source_unverified",
                    "unverified_fusion_consensus",
                ]
            },
        }
    )
    assert view["review_reasons"] == ["Lời chép mới có một nguồn ghi để đối chiếu."]


@pytest.mark.parametrize(
    "primary,other",
    [
        ("hạn ngày sáu tháng mười", "hạn ngày sáu tháng thôi"),
        ("chưa đồng ý", "đã đồng ý"),
        ("tôi kết luận", "tôi kích luận"),
        ("chất lượng tên file", "chất lượng tới phai"),
    ],
)
def test_uncalibrated_correlated_microphones_do_not_overwrite_primary_utterance(primary, other):
    hypotheses = {}
    for source, text, score in [("a", primary, 0.8), ("b", other, 0.75), ("c", other, 0.7)]:
        hypotheses[source] = SourceHypothesis(
            meeting_id="m",
            segment_id="t",
            source_id=source,
            text=text,
            transcript_quality_score=score,
            asr_status="transcribed",
            asr_features={"mean_confidence": None},
        )
    text, decisions = fuse_f5_rule_weighted_corrected(
        build_confusion_network(hypotheses), hypotheses
    )
    assert text == primary and all(d["needs_review"] for d in decisions)
    assert all(d["representative_source_id"] == "a" for d in decisions)


def test_source_alternatives_are_distinct_accepted_texts_without_internal_fields():
    row = {
        "_id": "row",
        "text": "ban đầu",
        "data": {
            "source_evidence": [
                {
                    "source_id": "source-1",
                    "asr_status": "transcribed",
                    "candidate_scores": {"transcript": "ban đầu"},
                },
                {
                    "source_id": "source-2",
                    "asr_status": "transcribed",
                    "candidate_scores": {"transcript": "bản khác"},
                },
                {
                    "source_id": "source-3",
                    "asr_status": "transcribed",
                    "candidate_scores": {"transcript": "bản khác"},
                },
                {
                    "source_id": "source-4",
                    "asr_status": "unreliable",
                    "candidate_scores": {"transcript": "đã loại"},
                },
            ]
        },
    }
    assert view_row(row)["source_candidates"] == [{"label": "Nguồn ghi 2", "text": "bản khác"}]


def _context_fixture(tmp_path, core_start, core_end):
    class Collection:
        def __init__(self, document):
            self.document = document

        def find_one(self, query):
            return (
                self.document if all(self.document.get(k) == v for k, v in query.items()) else None
            )

    (tmp_path / "audio.wav").write_bytes(b"audio")
    source = {"_id": "asset", "owner_id": "owner", "meeting_id": "meeting", "artifact_id": "audio"}
    artifact = {"_id": "audio", "owner_id": "owner", "resource_id": "meeting", "path": "audio.wav"}
    mongo = SimpleNamespace(
        db=SimpleNamespace(sources=Collection(source), artifacts=Collection(artifact)),
        settings=SimpleNamespace(data_dir=tmp_path),
    )
    meeting = {
        "_id": "meeting",
        "owner_id": "owner",
        "timeline": {
            "clips": [
                {
                    "id": "part",
                    "asset_id": "asset",
                    "source_in_ms": 5000,
                    "source_out_ms": 15000,
                }
            ]
        },
    }
    row = {
        "start_sec": 40,
        "end_sec": 40.2,
        "needs_review": True,
        "data": {
            "selected_recording_evidence": [
                {
                    "asset_id": "asset",
                    "clip_id": "part",
                    "source_start_sec": core_start,
                    "source_end_sec": core_end,
                }
            ],
        },
    }
    return mongo, meeting, row


@pytest.mark.parametrize(
    "start,end,window", [(5, 5.2, (5, 7.2)), (10, 10.2, (8, 12.2)), (14.7, 14.9, (12.7, 15))]
)
def test_review_context_uses_original_source_clock_and_stays_inside_recording(
    tmp_path, start, end, window
):
    mongo, meeting, row = _context_fixture(tmp_path, start, end)
    context = review_context(mongo, meeting, row)
    assert (context["start_sec"], context["end_sec"]) == pytest.approx(window)
    assert context["audio"]["url"] == "/api/v1/artifacts/audio"
    assert "path" not in context["audio"]


@pytest.mark.parametrize(
    "invalid", ["source_owner", "artifact_owner", "clip", "missing_file", "missing_time"]
)
def test_review_context_never_leaks_other_sources_or_fabricates_missing_mapping(tmp_path, invalid):
    mongo, meeting, row = _context_fixture(tmp_path, 10, 10.2)
    if invalid == "source_owner":
        mongo.db.sources.document["owner_id"] = "someone-else"
    elif invalid == "artifact_owner":
        mongo.db.artifacts.document["owner_id"] = "someone-else"
    elif invalid == "clip":
        meeting["timeline"]["clips"] = []
    elif invalid == "missing_file":
        (tmp_path / "audio.wav").unlink()
    else:
        row["data"]["selected_recording_evidence"][0].pop("source_start_sec")
    assert review_context(mongo, meeting, row) is None


def test_view_row_populates_speaker_and_audio_fallback_review_reasons():
    row = {
        "_id": "s1",
        "needs_review": True,
        "text": "xin chào",
        "data": {
            "warnings": ["speaker_identity_inconsistent_with_track"],
            "speaker": {"warnings": ["speaker_track_unresolved"], "needs_review": True},
            "fusion_method": "AUDIO_DELAY_AND_SUM",
            "routing_metadata": {"audio_fusion": {"fallback_reason": "uncertain_local_delay"}},
        },
    }
    reasons = view_row(row)["review_reasons"]
    assert len(reasons) == 3
    assert any("không nhất quán" in r or "chưa nhất quán" in r for r in reasons)
    assert any("người nói" in r for r in reasons)
    assert any("micro" in r for r in reasons)

