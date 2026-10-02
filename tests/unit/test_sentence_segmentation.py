"""Unit tests for sentence segmentation."""

from __future__ import annotations

from meeting_pipeline.domain.transcription import TimedWord
from meeting_pipeline.pipeline.stages.sentence_segmentation import segment_sentences


def test_split_on_ending_punctuation() -> None:
    """Sentences are split on ending punctuation (. ? ! …) but NOT on comma (,)."""
    words = [
        TimedWord(text="Hôm", start_sec=1.0, end_sec=1.5),
        TimedWord(text="nay,", start_sec=1.5, end_sec=2.0),  # Comma should NOT split
        TimedWord(text="trời", start_sec=2.0, end_sec=2.5),
        TimedWord(text="mưa.", start_sec=2.5, end_sec=3.0),  # Period MUST split
        TimedWord(text="Bạn", start_sec=3.2, end_sec=3.7),
        TimedWord(text="khỏe", start_sec=3.7, end_sec=4.2),
        TimedWord(text="không?", start_sec=4.2, end_sec=4.8),  # Question mark MUST split
    ]

    sentences = segment_sentences(words, sentence_pause_seconds=0.8, max_sentence_seconds=15.0)

    assert len(sentences) == 2
    assert sentences[0].text == "Hôm nay, trời mưa."
    assert sentences[0].start_sec == 1.0
    assert sentences[0].end_sec == 3.0

    assert sentences[1].text == "Bạn khỏe không?"
    assert sentences[1].start_sec == 3.2
    assert sentences[1].end_sec == 4.8


def test_split_on_acoustic_pause() -> None:
    """Sentences are split when pause between words >= sentence_pause_seconds (0.8s)."""
    words = [
        TimedWord(text="chúng", start_sec=1.0, end_sec=1.5),
        TimedWord(text="ta", start_sec=1.5, end_sec=2.0),
        # Gap from 2.0 to 3.0 is 1.0s >= 0.8s -> MUST SPLIT
        TimedWord(text="tiếp", start_sec=3.0, end_sec=3.5),
        TimedWord(text="tục", start_sec=3.5, end_sec=4.0),
    ]

    sentences = segment_sentences(words, sentence_pause_seconds=0.8, max_sentence_seconds=15.0)

    assert len(sentences) == 2
    assert sentences[0].text == "chúng ta"
    assert sentences[1].text == "tiếp tục"


def test_split_on_speaker_boundary() -> None:
    """Sentences are split when the speaker turn changes."""
    words = [
        TimedWord(text="tôi", start_sec=1.0, end_sec=1.5),
        TimedWord(text="đồng", start_sec=1.5, end_sec=2.0),
        TimedWord(text="ý", start_sec=2.0, end_sec=2.4),
        TimedWord(text="tôi", start_sec=2.5, end_sec=3.0),
        TimedWord(text="cũng", start_sec=3.0, end_sec=3.5),
        TimedWord(text="vậy", start_sec=3.5, end_sec=4.0),
    ]
    speaker_turns = [
        {"speaker_id": "alice", "start_sec": 0.0, "end_sec": 2.45},
        {"speaker_id": "bob", "start_sec": 2.45, "end_sec": 5.0},
    ]

    sentences = segment_sentences(
        words,
        sentence_pause_seconds=0.8,
        max_sentence_seconds=15.0,
        speaker_turns=speaker_turns,
    )

    assert len(sentences) == 2
    assert sentences[0].text == "tôi đồng ý"
    assert sentences[0].speaker_id == "alice"
    assert sentences[1].text == "tôi cũng vậy"
    assert sentences[1].speaker_id == "bob"


def test_split_when_exceeding_max_sentence_seconds() -> None:
    """Sentences are split when duration exceeds max_sentence_seconds (15s)."""
    # Create words spanning 20 seconds without punctuation
    words = [
        TimedWord(text=f"từ_{i}", start_sec=float(i), end_sec=float(i) + 0.8) for i in range(20)
    ]

    sentences = segment_sentences(words, sentence_pause_seconds=1.0, max_sentence_seconds=15.0)

    assert len(sentences) >= 2
    for s in sentences:
        assert (s.end_sec - s.start_sec) <= 16.0


def test_short_fragment_merged() -> None:
    """A single short word followed closely by another sentence of the same speaker is merged."""
    words = [
        TimedWord(text="Vâng", start_sec=1.0, end_sec=1.3),
        # Gap of 0.2s to next word
        TimedWord(text="tôi", start_sec=1.5, end_sec=2.0),
        TimedWord(text="hiểu.", start_sec=2.0, end_sec=2.5),
    ]

    sentences = segment_sentences(words, sentence_pause_seconds=0.8, max_sentence_seconds=15.0)

    # "Vâng" should be merged into "Vâng tôi hiểu."
    assert len(sentences) == 1
    assert sentences[0].text == "Vâng tôi hiểu."


def test_zero_duration_sentence_marked_review() -> None:
    """Sentences with zero duration are flagged for review."""
    words = [
        TimedWord(text="ảo_giác", start_sec=2.0, end_sec=2.0),
    ]

    sentences = segment_sentences(words, sentence_pause_seconds=0.8, max_sentence_seconds=15.0)

    assert len(sentences) == 1
    assert sentences[0].needs_review is True
    assert "zero_duration_sentence" in sentences[0].warnings
