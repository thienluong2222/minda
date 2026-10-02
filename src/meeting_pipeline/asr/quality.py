"""Model-independent checks for implausible ASR hypotheses.

These are rejection rules, not calibrated probabilities. Thresholds are intentionally
conservative and must be tuned against independent VIVOS validation recordings.
"""

from __future__ import annotations

import re
import zlib
from collections.abc import Sequence
from dataclasses import dataclass

from meeting_pipeline.config import AsrConfig
from meeting_pipeline.domain.transcription import TimedWord


@dataclass(frozen=True)
class AsrQualityCheck:
    """An audit-friendly decision for one decode candidate."""

    accepted: bool
    issues: tuple[str, ...]
    words_per_second: float
    compression_ratio: float | None


def check_asr_quality(
    text: str,
    words: Sequence[TimedWord],
    duration_sec: float,
    config: AsrConfig,
    *,
    parse_warnings: Sequence[str] = (),
) -> AsrQualityCheck:
    """Reject impossible rates, repetition and missing/out-of-range word alignment."""
    issues = list(parse_warnings)
    tokens = re.findall(r"\w+", text.casefold(), flags=re.UNICODE)
    duration = max(duration_sec, 1e-6)
    rate = len(tokens) / duration

    if not tokens:
        issues.append("asr_empty")
    elif not words:
        issues.append("word_timestamps_missing")
    if "unk" in tokens:
        # PhoWhisper can emit this tokenizer placeholder on heavily separated
        # overlap audio; it is not a spoken Vietnamese word to publish.
        issues.append("asr_unknown_token")

    # A small fixed allowance avoids rejecting natural short interjections.
    if len(tokens) > max(12, duration_sec * config.max_words_per_second + 4):
        issues.append("implausible_word_rate")

    if _max_consecutive_repeat(tokens) >= config.max_consecutive_token_repeats:
        issues.append("repeated_word")
    if any(
        _max_consecutive_phrase_repeat(tokens, n) >= config.max_consecutive_ngram_repeats
        for n in (2, 3)
    ):
        issues.append("repeated_ngram")
    if len(tokens) >= 10 and _has_repeated_long_phrase(tokens, width=5):
        issues.append("repeated_long_phrase")
    if re.search(rf"([^\w\s])\1{{{config.max_consecutive_punctuation - 1},}}", text):
        issues.append("repeated_punctuation")

    encoded = text.encode("utf-8")
    compression = len(zlib.compress(encoded)) / len(encoded) if encoded else None
    if (
        compression is not None
        and len(tokens) >= 12
        and len(encoded) >= 80
        and compression < config.min_compression_ratio
    ):
        issues.append("repetitive_text_compression")

    tolerance = config.timestamp_tolerance_seconds
    previous_start = -1.0
    previous_end = -1.0
    for word in words:
        if (
            word.start_sec < -tolerance
            or word.end_sec > duration_sec + tolerance
            or word.end_sec < word.start_sec
        ):
            issues.append("word_timestamp_out_of_clip")
            break
        if word.start_sec + tolerance < previous_start or word.end_sec + tolerance < previous_end:
            issues.append("word_timestamps_nonmonotonic")
            break
        previous_start = word.start_sec
        previous_end = word.end_sec

    if tokens and words and len(words) < len(tokens) / 2:
        issues.append("word_timestamps_incomplete")

    unique_issues = tuple(dict.fromkeys(issues))
    return AsrQualityCheck(
        accepted=not unique_issues,
        issues=unique_issues,
        words_per_second=round(rate, 3),
        compression_ratio=round(compression, 4) if compression is not None else None,
    )


def _max_consecutive_repeat(items: Sequence[object]) -> int:
    longest = 0
    current = 0
    previous: object = None
    for item in items:
        current = current + 1 if item == previous else 1
        longest = max(longest, current)
        previous = item
    return longest


def _max_consecutive_phrase_repeat(tokens: Sequence[str], width: int) -> int:
    longest = 0
    for start in range(len(tokens) - width + 1):
        phrase = tokens[start : start + width]
        count = 1
        position = start + width
        while position + width <= len(tokens) and tokens[position : position + width] == phrase:
            count += 1
            position += width
        longest = max(longest, count)
    return longest


def _has_repeated_long_phrase(tokens: Sequence[str], width: int) -> bool:
    seen: set[tuple[str, ...]] = set()
    for start in range(len(tokens) - width + 1):
        phrase = tuple(tokens[start : start + width])
        if phrase in seen:
            return True
        seen.add(phrase)
    return False
