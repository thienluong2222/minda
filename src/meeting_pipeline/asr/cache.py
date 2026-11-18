"""Disk and in-memory caching for ASR decoding results.

Invalidated whenever audio waveform, sampling rate, model ID, model revision,
or decoding settings change.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import numpy as np

from meeting_pipeline.adapters.phowhisper_asr import ASR_DECODING_POLICY_VERSION, AsrResult
from meeting_pipeline.config import AsrConfig
from meeting_pipeline.domain.transcription import TimedWord

logger = logging.getLogger(__name__)


def decoding_fingerprint(config: AsrConfig) -> dict[str, Any]:
    """Raw cached acceptance depends on decoding and quality checks, not audio alone."""
    return {
        "policy_version": ASR_DECODING_POLICY_VERSION,
        "mlx_policy_version": "single_window_alignment_v1",
        **config.model_dump(
            include={
                "runtime",
                "auto_backend",
                "mlx_model_dir",
                "language",
                "max_new_tokens_per_second",
                "min_new_tokens",
                "max_new_tokens",
                "max_decode_attempts",
                "max_words_per_second",
                "max_consecutive_token_repeats",
                "max_consecutive_ngram_repeats",
                "max_consecutive_punctuation",
                "min_compression_ratio",
                "timestamp_tolerance_seconds",
            }
        ),
    }


def compute_asr_cache_key(
    waveform: np.ndarray,
    sample_rate: int,
    model_id: str,
    model_revision: str,
    decoding_settings: dict[str, Any] | None = None,
) -> str:
    """Compute a deterministic SHA-256 cache key for an audio segment and decoding context."""
    hasher = hashlib.sha256()

    # Audio content: use float32 byte representation
    audio_bytes = np.ascontiguousarray(waveform, dtype=np.float32).tobytes()
    hasher.update(audio_bytes)
    hasher.update(str(sample_rate).encode("utf-8"))
    hasher.update(model_id.encode("utf-8"))
    hasher.update(model_revision.encode("utf-8"))

    if decoding_settings:
        # Canonical JSON serialization of decoding settings
        settings_str = json.dumps(decoding_settings, sort_keys=True, default=str)
        hasher.update(settings_str.encode("utf-8"))

    return hasher.hexdigest()


class AsrCache:
    """Two-tier (in-memory + disk) cache for AsrResult objects."""

    def __init__(self, cache_dir: Path | None = None, enabled: bool = True) -> None:
        self.enabled = enabled
        self.cache_dir = cache_dir
        if self.enabled and self.cache_dir is not None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._memory_cache: dict[str, AsrResult] = {}

    def get(self, key: str) -> AsrResult | None:
        """Retrieve cached AsrResult by key, returning None on cache miss."""
        if not self.enabled:
            return None

        # Tier 1: In-memory
        if key in self._memory_cache:
            return self._memory_cache[key]

        # Tier 2: Disk
        if self.cache_dir is None:
            return None

        cache_file = self.cache_dir / f"{key}.json"
        if not cache_file.exists():
            return None

        try:
            with open(cache_file, encoding="utf-8") as f:
                data = json.load(f)

            words = [
                TimedWord(
                    text=w["text"],
                    start_sec=w["start_sec"],
                    end_sec=w["end_sec"],
                    confidence=w.get("confidence"),
                )
                for w in data.get("words", [])
            ]
            result = AsrResult(
                text=data.get("text", ""),
                words=words,
                status=data.get("status", "transcribed"),
                warnings=data.get("warnings", []),
                raw_candidates=data.get("raw_candidates", []),
            )
            self._memory_cache[key] = result
            return result
        except Exception as exc:
            logger.warning("Failed to read ASR cache file %s: %s", cache_file, exc)
            return None

    def put(self, key: str, result: AsrResult) -> None:
        """Store an AsrResult into both memory and disk tiers."""
        if not self.enabled:
            return

        self._memory_cache[key] = result

        if self.cache_dir is None:
            return

        cache_file = self.cache_dir / f"{key}.json"
        try:
            payload = {
                "text": result.text,
                "words": [w.model_dump() for w in result.words],
                "status": result.status,
                "warnings": result.warnings,
                "raw_candidates": result.raw_candidates,
            }
            tmp_file = cache_file.with_suffix(".tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            tmp_file.replace(cache_file)
        except Exception as exc:
            logger.warning("Failed to write ASR cache file %s: %s", cache_file, exc)
