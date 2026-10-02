"""Sentence segmentation from timed words with syntactic and acoustic boundaries."""

from __future__ import annotations

import re
import uuid
from typing import Any

from pydantic import BaseModel, Field

from meeting_pipeline.domain.transcription import SpeechRegion, TimedWord

_SENTENCE_END_PUNCT = re.compile(r"[.?!…]+$")


class SegmentedSentence(BaseModel):
    """Clean sentence with verified start/end boundaries and associated timed words."""

    sentence_id: str
    text: str
    start_sec: float
    end_sec: float
    words: list[TimedWord]
    speaker_id: str | None = None
    speaker_label: str | None = None
    speaker_status: str = "unknown"
    needs_review: bool = False
    speech_region_id: str | None = None
    warnings: list[str] = Field(default_factory=list)


def _get_speaker_for_word(
    word: TimedWord,
    speaker_turns: list[dict[str, Any]] | None,
) -> str | None:
    if not speaker_turns:
        return None
    midpoint = (word.start_sec + word.end_sec) / 2.0
    for turn in speaker_turns:
        if turn.get("start_sec", 0.0) <= midpoint < turn.get("end_sec", float("inf")):
            return str(turn.get("speaker_id")) if turn.get("speaker_id") else None
    return None


def segment_sentences(
    words: list[TimedWord],
    sentence_pause_seconds: float = 0.8,
    max_sentence_seconds: float = 15.0,
    speaker_turns: list[dict[str, Any]] | None = None,
    speech_regions: list[SpeechRegion] | None = None,
) -> list[SegmentedSentence]:
    """Segment a stream of timed words into sentences according to Section 10.1 priority."""
    if not words:
        return []

    # Map words to speech regions if provided
    region_map: dict[int, str | None] = {}
    if speech_regions:
        for idx, w in enumerate(words):
            mid = (w.start_sec + w.end_sec) / 2.0
            matched_reg = None
            for reg in speech_regions:
                if reg.start_sec - 1e-4 <= mid <= reg.end_sec + 1e-4:
                    matched_reg = reg.region_id
                    break
            region_map[idx] = matched_reg
    else:
        region_map = {idx: None for idx in range(len(words))}

    sentences: list[SegmentedSentence] = []
    current_words: list[TimedWord] = []
    current_start = words[0].start_sec

    for idx, word in enumerate(words):
        current_words.append(word)

        # Check if we should split after this word
        should_split = False

        if idx + 1 < len(words):
            next_word = words[idx + 1]

            # 1. Speaker turn boundary
            if speaker_turns:
                curr_spk = _get_speaker_for_word(word, speaker_turns)
                next_spk = _get_speaker_for_word(next_word, speaker_turns)
                if curr_spk != next_spk:
                    should_split = True

            # 2. Sentence-ending punctuation (., ?, !, …) but NOT comma (,)
            if not should_split and _SENTENCE_END_PUNCT.search(word.text):
                should_split = True

            # 3. Acoustic pause >= sentence_pause_seconds
            pause = next_word.start_sec - word.end_sec
            if not should_split and pause >= sentence_pause_seconds - 1e-4:
                should_split = True

            # 4. Max sentence duration exceeded
            dur_if_next = next_word.end_sec - current_start
            if not should_split and dur_if_next > max_sentence_seconds:
                should_split = True

            # 5. Speech region boundary change
            if not should_split and region_map.get(idx) != region_map.get(idx + 1):
                should_split = True
        else:
            # End of words
            should_split = True

        if should_split and current_words:
            s_start = current_words[0].start_sec
            s_end = current_words[-1].end_sec
            text = " ".join(w.text for w in current_words).strip()
            reg_id = region_map.get(idx - len(current_words) + 1)
            spk_id = _get_speaker_for_word(current_words[0], speaker_turns)

            needs_review = False
            warnings: list[str] = []
            if s_end - s_start <= 1e-5:
                needs_review = True
                warnings.append("zero_duration_sentence")

            sentences.append(
                SegmentedSentence(
                    sentence_id=str(uuid.uuid4()),
                    text=text,
                    start_sec=round(s_start, 4),
                    end_sec=round(s_end, 4),
                    words=list(current_words),
                    speaker_id=spk_id,
                    speaker_label=None,
                    speaker_status="identified" if spk_id else "unknown",
                    needs_review=needs_review,
                    speech_region_id=reg_id,
                    warnings=warnings,
                )
            )
            current_words = []
            if idx + 1 < len(words):
                current_start = words[idx + 1].start_sec

    # Short fragment merge: if a sentence has <= 1 word and is short,
    # merge with next if same speaker and small gap
    merged_sentences: list[SegmentedSentence] = []
    i = 0
    while i < len(sentences):
        curr = sentences[i]
        if (
            len(curr.words) == 1
            and (curr.end_sec - curr.start_sec) < 1.0
            and i + 1 < len(sentences)
        ):
            nxt = sentences[i + 1]
            gap = nxt.start_sec - curr.end_sec
            comb_dur = nxt.end_sec - curr.start_sec
            same_spk = curr.speaker_id == nxt.speaker_id
            if gap <= 0.6 and comb_dur <= max_sentence_seconds and same_spk:
                # Merge into next sentence
                merged_words = curr.words + nxt.words
                merged_sentences.append(
                    SegmentedSentence(
                        sentence_id=nxt.sentence_id,
                        text=f"{curr.text} {nxt.text}".strip(),
                        start_sec=curr.start_sec,
                        end_sec=nxt.end_sec,
                        words=merged_words,
                        speaker_id=nxt.speaker_id,
                        speaker_label=nxt.speaker_label,
                        speaker_status=nxt.speaker_status,
                        needs_review=nxt.needs_review,
                        speech_region_id=nxt.speech_region_id or curr.speech_region_id,
                        warnings=curr.warnings + nxt.warnings,
                    )
                )
                i += 2
                continue
        merged_sentences.append(curr)
        i += 1

    return merged_sentences


class SentenceSegmenter:
    """Service to partition stitched word streams into readable sentences."""

    def __init__(
        self,
        sentence_pause_seconds: float = 0.8,
        max_sentence_seconds: float = 15.0,
    ) -> None:
        self.sentence_pause_seconds = sentence_pause_seconds
        self.max_sentence_seconds = max_sentence_seconds

    def segment(
        self,
        words: list[TimedWord],
        speaker_turns: list[dict[str, Any]] | None = None,
        speech_regions: list[SpeechRegion] | None = None,
    ) -> list[SegmentedSentence]:
        return segment_sentences(
            words=words,
            sentence_pause_seconds=self.sentence_pause_seconds,
            max_sentence_seconds=self.max_sentence_seconds,
            speaker_turns=speaker_turns,
            speech_regions=speech_regions,
        )
