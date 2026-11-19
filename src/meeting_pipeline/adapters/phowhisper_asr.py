"""PhoWhisper speech recognition adapter with word/segment timestamps."""

from __future__ import annotations

import logging
import math
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, Field

from meeting_pipeline.asr.model_selection import resolve_model_snapshot
from meeting_pipeline.asr.quality import check_asr_quality
from meeting_pipeline.config import AsrConfig
from meeting_pipeline.domain.transcription import AsrChunk, ChunkTranscript, TimedWord

logger = logging.getLogger(__name__)
ASR_DECODING_POLICY_VERSION = "deterministic_beam_retry_v2"


class AsrResult(BaseModel):
    """Raw transcription output from an ASR model on a local clip."""

    text: str
    words: list[TimedWord]
    status: Literal["transcribed", "empty", "failed", "unreliable"]
    warnings: list[str] = Field(default_factory=list)
    raw_candidates: list[dict[str, Any]] = Field(default_factory=list)


class BaseAsrAdapter(ABC):
    """Abstract interface for speech-to-text adapters."""

    @abstractmethod
    def transcribe(
        self,
        waveform: np.ndarray,
        sample_rate: int = 16000,
    ) -> AsrResult:
        """Transcribe a mono float32 waveform and return text with local clip timestamps."""
        raise NotImplementedError

    def transcribe_chunk(
        self,
        chunk: AsrChunk,
        waveform: np.ndarray,
        sample_rate: int = 16000,
    ) -> ChunkTranscript:
        """Transcribe an AsrChunk and map word timestamps to meeting time."""
        if waveform.size == 0 or np.max(np.abs(waveform), initial=0.0) < 1e-6:
            return ChunkTranscript(
                chunk_id=chunk.chunk_id,
                raw_text="",
                words=[],
                status="empty",
                warnings=["empty_audio"],
            )

        try:
            result = self.transcribe(waveform, sample_rate)
        except Exception as exc:
            logger.warning("ASR failed for chunk %s: %s", chunk.chunk_id, exc)
            return ChunkTranscript(
                chunk_id=chunk.chunk_id,
                raw_text="",
                words=[],
                status="failed",
                warnings=[f"asr_exception: {exc}"],
            )

        if result.status == "unreliable":
            return ChunkTranscript(
                chunk_id=chunk.chunk_id,
                raw_text="",
                words=[],
                status="unreliable",
                warnings=result.warnings,
            )

        # Convert local word timestamps to meeting-time coordinates
        meeting_words: list[TimedWord] = []
        clip_start = chunk.clip_interval.start_sec

        for word in result.words:
            abs_start = round(clip_start + word.start_sec, 4)
            abs_end = round(clip_start + word.end_sec, 4)
            if abs_end < abs_start:
                abs_end = abs_start
            meeting_words.append(
                TimedWord(
                    text=word.text,
                    start_sec=abs_start,
                    end_sec=abs_end,
                    confidence=word.confidence,
                )
            )

        return ChunkTranscript(
            chunk_id=chunk.chunk_id,
            raw_text=result.text,
            words=meeting_words,
            status=result.status,
            warnings=result.warnings,
        )


class PhoWhisperAsrAdapter(BaseAsrAdapter):
    """Production adapter for PhoWhisper with word timestamp extraction."""

    def __init__(self, config: AsrConfig, cache_dir: Path) -> None:
        self.config = config
        self.cache_dir = cache_dir
        self._pipeline: Any = None
        self._cpu_fallback = None

    def _load_pipeline(self) -> Any:
        if self._pipeline is not None:
            return self._pipeline

        snapshot = resolve_model_snapshot(self.config, self.cache_dir)

        if self.config.runtime == "mlx" or (
            self.config.runtime == "auto" and self.config.auto_backend == "mlx"
        ):
            from meeting_pipeline.adapters.mlx_asr import MlxWhisperPipeline

            try:
                self._pipeline = MlxWhisperPipeline(self.config, self.cache_dir)
                return self._pipeline
            except (OSError, ValueError):
                if self.config.runtime == "mlx":
                    raise
                logger.warning("MLX runtime unavailable; using CPU with the pinned checkpoint")

        import torch
        from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline

        device = "cpu"
        if self.config.runtime == "mps" or (
            self.config.runtime == "auto" and self.config.auto_backend == "mps"
        ):
            if torch.backends.mps.is_available():
                device = "mps"
            elif self.config.runtime == "mps":
                raise RuntimeError("MPS không khả dụng; chọn runtime=cpu hoặc auto.")

        processor = AutoProcessor.from_pretrained(  # type: ignore[no-untyped-call]
            snapshot, local_files_only=True
        )
        model = AutoModelForSpeechSeq2Seq.from_pretrained(snapshot, local_files_only=True)
        if device == "mps":
            model = model.to(dtype=torch.float16)

        self._pipeline = pipeline(
            "automatic-speech-recognition",
            model=model,
            tokenizer=processor.tokenizer,
            feature_extractor=processor.feature_extractor,
            return_timestamps="word",
            device=device,
        )
        return self._pipeline

    def transcribe(
        self,
        waveform: np.ndarray,
        sample_rate: int = 16000,
    ) -> AsrResult:
        if waveform.size == 0 or np.max(np.abs(waveform), initial=0.0) < 1e-6:
            return AsrResult(text="", words=[], status="empty", warnings=["empty_audio"])

        pipe = self._load_pipeline()
        samples = np.asarray(waveform, dtype=np.float32)
        duration_sec = len(samples) / sample_rate
        max_tokens = min(
            self.config.max_new_tokens,
            max(
                self.config.min_new_tokens,
                math.ceil(duration_sec * self.config.max_new_tokens_per_second),
            ),
        )
        raw_candidates: list[dict[str, Any]] = []
        issues: list[str] = []

        runtime = str(getattr(pipe, "device", "cpu"))
        # This MLX bridge implements one greedy window, not HF beam search.
        # Repeating it with num_beams=3 would decode the identical request twice.
        attempts = 1 if runtime == "mlx" else self.config.max_decode_attempts
        for attempt in range(attempts):
            decoding = self._decoding_settings(attempt, max_tokens)
            try:
                output = pipe(samples, generate_kwargs=decoding)
            except Exception as exc:
                raw_candidates.append(
                    {"attempt": attempt + 1, "decoding": decoding, "error": str(exc)}
                )
                issues.append("model_generation_error")
                continue

            raw_text, words, parse_warnings = self._parse_output(output)
            check = check_asr_quality(
                raw_text, words, duration_sec, self.config, parse_warnings=parse_warnings
            )
            raw_candidates.append(
                {
                    "attempt": attempt + 1,
                    "runtime": runtime,
                    "decoding": decoding,
                    "text": raw_text,
                    "words": [word.model_dump() for word in words],
                    "quality": {
                        "accepted": check.accepted,
                        "issues": list(check.issues),
                        "words_per_second": check.words_per_second,
                        "compression_ratio": check.compression_ratio,
                    },
                }
            )
            if check.accepted:
                return AsrResult(
                    text=raw_text,
                    words=words,
                    status="transcribed",
                    warnings=["asr_retry_succeeded"] if attempt else [],
                    raw_candidates=raw_candidates,
                )
            issues.extend(check.issues)

        # Do not expose a rejected candidate as the main transcript.
        failed_all_generations = all("error" in candidate for candidate in raw_candidates)
        empty_all_generations = bool(raw_candidates) and all(
            candidate.get("quality", {}).get("issues") == ["asr_empty"]
            for candidate in raw_candidates
        )
        if (
            self.config.runtime == "auto"
            and runtime != "cpu"
            and not empty_all_generations
            and duration_sec >= 0.8
        ):
            logger.warning(
                "Accelerated ASR failed quality checks; retrying the same checkpoint on CPU"
            )
            if self._cpu_fallback is None:
                self._cpu_fallback = PhoWhisperAsrAdapter(
                    self.config.model_copy(update={"runtime": "cpu"}), self.cache_dir
                )
            result = self._cpu_fallback.transcribe(samples, sample_rate)
            result.warnings = list(dict.fromkeys([*result.warnings, "asr_cpu_fallback"]))
            result.raw_candidates = [*raw_candidates, *result.raw_candidates]
            return result
        return AsrResult(
            text="",
            words=[],
            status=(
                "failed"
                if failed_all_generations
                else "empty"
                if empty_all_generations
                else "unreliable"
            ),
            warnings=list(dict.fromkeys(issues)),
            raw_candidates=raw_candidates,
        )

    def _decoding_settings(self, attempt: int, max_tokens: int) -> dict[str, Any]:
        """Bound generation on both attempts; vary the second decode to escape loops."""
        settings: dict[str, Any] = {
            "language": self.config.language,
            "task": "transcribe",
            "max_new_tokens": max_tokens,
            "do_sample": False,
        }
        if attempt:
            settings.update(
                {
                    "num_beams": 3,
                }
            )
        return settings

    @staticmethod
    def _parse_output(output: Any) -> tuple[str, list[TimedWord], list[str]]:
        raw_text = str(output.get("text", "")).strip()
        words: list[TimedWord] = []
        warnings: list[str] = []
        for chunk in output.get("chunks", []):
            text = str(chunk.get("text", "")).strip()
            if not text:
                continue
            timestamps = chunk.get("timestamp")
            if not isinstance(timestamps, tuple | list) or len(timestamps) != 2:
                warnings.append("word_timestamp_invalid")
                continue
            try:
                start, end = float(timestamps[0]), float(timestamps[1])
                if not math.isfinite(start) or not math.isfinite(end) or end < start:
                    raise ValueError("invalid word timestamp")
                conf_raw = chunk.get("confidence")
                conf: float | None = None
                if conf_raw is not None:
                    parsed_conf = float(conf_raw)
                    if math.isfinite(parsed_conf):
                        conf = min(1.0, max(0.0, parsed_conf))
                words.append(TimedWord(text=text, start_sec=start, end_sec=end, confidence=conf))
            except (TypeError, ValueError):
                warnings.append("word_timestamp_invalid")
        return raw_text, words, warnings


class FakeAsrAdapter(BaseAsrAdapter):
    """Test double for ASR adapter that returns configured results without ML models."""

    def __init__(
        self,
        results: list[AsrResult] | None = None,
        default_result: AsrResult | None = None,
        should_raise: Exception | None = None,
    ) -> None:
        self.results = list(results or [])
        self.default_result = default_result or AsrResult(
            text="mẫu văn bản kiểm thử",
            words=[
                TimedWord(text="mẫu", start_sec=0.0, end_sec=0.5),
                TimedWord(text="văn", start_sec=0.5, end_sec=1.0),
                TimedWord(text="bản", start_sec=1.0, end_sec=1.5),
                TimedWord(text="kiểm", start_sec=1.5, end_sec=2.0),
                TimedWord(text="thử", start_sec=2.0, end_sec=2.5),
            ],
            status="transcribed",
        )
        self.should_raise = should_raise
        self._call_count = 0

    def transcribe(
        self,
        waveform: np.ndarray,
        sample_rate: int = 16000,
    ) -> AsrResult:
        if self.should_raise:
            raise self.should_raise

        if waveform.size == 0 or np.max(np.abs(waveform), initial=0.0) < 1e-6:
            return AsrResult(text="", words=[], status="empty", warnings=["empty_audio"])

        if self.results and self._call_count < len(self.results):
            res = self.results[self._call_count]
            self._call_count += 1
            return res

        return self.default_result
