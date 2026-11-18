"""Regression cases for the Test1 hallucination and ASR audit behavior."""

from pathlib import Path

import numpy as np

from meeting_pipeline.adapters.phowhisper_asr import (
    AsrResult,
    FakeAsrAdapter,
    PhoWhisperAsrAdapter,
)
from meeting_pipeline.asr.model_selection import resolve_model_snapshot
from meeting_pipeline.asr.quality import check_asr_quality
from meeting_pipeline.asr.segment_asr import transcribe_segment_sources
from meeting_pipeline.config import AsrConfig, load_config
from meeting_pipeline.domain.contracts import MeetingSegment
from meeting_pipeline.domain.errors import ModelUnavailableError
from meeting_pipeline.domain.transcription import TimedWord


def _config() -> AsrConfig:
    return load_config(Path("configs/default.yaml")).asr


def test_test1_repetition_is_rejected_before_fusion() -> None:
    text = " ".join(["a"] * 217 + ["phủ"] * 7)
    words = [TimedWord(text=token, start_sec=0.0, end_sec=0.02) for token in text.split()]
    check = check_asr_quality(text, words, 2.42, _config())
    assert not check.accepted
    assert "implausible_word_rate" in check.issues
    assert "repeated_word" in check.issues

    segment = MeetingSegment(meeting_id="m1", segment_id="seg_0002", start_sec=9, end_sec=11.42)
    output = transcribe_segment_sources(
        "m1",
        segment,
        {"source-1": np.ones(38720, dtype=np.float32) * 0.1},
        FakeAsrAdapter(results=[AsrResult(text=text, words=words, status="transcribed")]),
    )["source-1"]
    assert output.asr_status == "unreliable"
    assert output.text == "" and output.words == []
    assert output.transcript_quality_score == 0
    assert output.raw_asr_candidates[0]["text"] == text


def test_good_short_utterance_with_word_alignment_passes() -> None:
    words = [TimedWord(text="dạ", start_sec=0.0, end_sec=0.3)]
    assert check_asr_quality("dạ", words, 0.35, _config()).accepted


def test_repeated_sentence_and_punctuation_are_rejected() -> None:
    text = "cô cứ nhè cái nọng cái chê cô cứ nhè cái nọng cái chê"
    words = [
        TimedWord(text=token, start_sec=index * 0.15, end_sec=(index + 1) * 0.15)
        for index, token in enumerate(text.split())
    ]
    assert "repeated_long_phrase" in check_asr_quality(text, words, 3.0, _config()).issues
    assert (
        "repeated_punctuation"
        in check_asr_quality(
            "dạ........", [TimedWord(text="dạ", start_sec=0, end_sec=0.3)], 1, _config()
        ).issues
    )


def test_unknown_token_from_separated_overlap_is_not_published() -> None:
    words = [
        TimedWord(text="giải", start_sec=0.0, end_sec=0.3),
        TimedWord(text="thưởng", start_sec=0.3, end_sec=0.7),
        TimedWord(text="unk", start_sec=0.7, end_sec=1.0),
    ]
    check = check_asr_quality("giải thưởng unk", words, 1.0, _config())
    assert not check.accepted
    assert "asr_unknown_token" in check.issues


def test_invalid_timestamps_and_missing_alignment_are_rejected() -> None:
    config = _config()
    assert "word_timestamps_missing" in check_asr_quality("xin chào", [], 1.0, config).issues
    words = [TimedWord(text="xin", start_sec=0.1, end_sec=2.0)]
    assert "word_timestamp_out_of_clip" in check_asr_quality("xin", words, 1.0, config).issues
    words = [
        TimedWord(text="xin", start_sec=0.7, end_sec=0.8),
        TimedWord(text="chào", start_sec=0.1, end_sec=0.2),
    ]
    assert (
        "word_timestamps_nonmonotonic" in check_asr_quality("xin chào", words, 1.0, config).issues
    )


def test_adapter_retries_once_and_never_publishes_rejected_candidate(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    outputs = [
        {
            "text": "a " * 100,
            "chunks": [{"text": "a", "timestamp": (0.0, 0.01)} for _ in range(100)],
        },
        {
            "text": "xin chào",
            "chunks": [
                {"text": "xin", "timestamp": (0.0, 0.4)},
                {"text": "chào", "timestamp": (0.4, 0.8)},
            ],
        },
    ]

    def fake_pipe(_wave: np.ndarray, *, generate_kwargs: dict[str, object]) -> dict[str, object]:
        calls.append(generate_kwargs)
        return outputs[len(calls) - 1]

    adapter = PhoWhisperAsrAdapter(_config(), tmp_path)
    adapter._pipeline = fake_pipe
    result = adapter.transcribe(np.ones(16000, dtype=np.float32) * 0.1)
    assert result.status == "transcribed" and result.text == "xin chào"
    assert len(result.raw_candidates) == 2
    assert calls[0]["max_new_tokens"] <= _config().max_new_tokens
    assert all(call["do_sample"] is False for call in calls)
    assert calls[1]["num_beams"] == 3


def test_adapter_marks_both_bad_decodes_unreliable(tmp_path: Path) -> None:
    adapter = PhoWhisperAsrAdapter(_config(), tmp_path)
    adapter._pipeline = lambda *_args, **_kwargs: {
        "text": "a " * 100,
        "chunks": [{"text": "a", "timestamp": (0.0, 0.01)} for _ in range(100)],
    }
    result = adapter.transcribe(np.ones(16000, dtype=np.float32) * 0.1)
    assert result.status == "unreliable"
    assert result.text == "" and result.words == []
    assert len(result.raw_candidates) == 2


def test_adapter_preserves_empty_and_generation_failure_statuses(tmp_path: Path) -> None:
    adapter = PhoWhisperAsrAdapter(_config(), tmp_path)
    adapter._pipeline = lambda *_args, **_kwargs: {"text": "", "chunks": []}
    empty = adapter.transcribe(np.ones(16000, dtype=np.float32) * 0.1)
    assert empty.status == "empty" and len(empty.raw_candidates) == 2

    def broken_pipe(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("decoder failed")

    adapter._pipeline = broken_pipe
    failed = adapter.transcribe(np.ones(16000, dtype=np.float32) * 0.1)
    assert failed.status == "failed"
    assert len(failed.raw_candidates) == 2
    assert failed.text == ""


def test_missing_word_probabilities_stay_null() -> None:
    segment = MeetingSegment(meeting_id="m1", segment_id="seg_0", start_sec=1, end_sec=2)
    result = AsrResult(
        text="xin chào",
        words=[
            TimedWord(text="xin", start_sec=0.1, end_sec=0.3),
            TimedWord(text="chào", start_sec=0.3, end_sec=0.5),
        ],
        status="transcribed",
    )
    hypothesis = transcribe_segment_sources(
        "m1",
        segment,
        {"phone": np.ones(16000, dtype=np.float32) * 0.1},
        FakeAsrAdapter(results=[result]),
    )["phone"]
    assert hypothesis.asr_features["mean_confidence"] is None
    assert all(word.asr_confidence is None for word in hypothesis.words)
    assert hypothesis.asr_features["word_agreement"] is None


def test_pinned_model_resolution_is_offline_and_fails_explicitly(tmp_path: Path) -> None:
    config = _config().for_variant("medium")
    try:
        resolve_model_snapshot(config, tmp_path)
    except ModelUnavailableError as exc:
        assert config.model_revision in str(exc)
    else:
        raise AssertionError("Missing checkpoint must not silently fall back")
