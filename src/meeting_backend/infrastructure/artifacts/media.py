"""Probe container metadata without importing any inference runtime."""

import shutil
from dataclasses import asdict

from meeting_backend.core.errors import AppError
from meeting_pipeline.adapters.audio_io import probe_audio as probe_audio_metadata
from meeting_pipeline.adapters.audio_io import validate_audio_duration
from meeting_pipeline.domain.errors import InvalidAudioError


def probe_audio(path, *, max_duration_seconds=None):
    binary = shutil.which("ffprobe")
    if not binary:
        raise AppError("FFPROBE_MISSING", "Cần FFmpeg/ffprobe để kiểm tra file âm thanh.", 503)
    try:
        metadata = probe_audio_metadata(path, timeout_sec=20)
    except InvalidAudioError as exc:
        raise AppError(
            "INVALID_AUDIO",
            "Không đọc được luồng âm thanh. Hãy kiểm tra file bằng trình phát "
            "hoặc xuất lại WAV/MP3.",
            422,
        ) from exc
    if max_duration_seconds is not None:
        try:
            validate_audio_duration(metadata, max_duration_seconds)
        except InvalidAudioError as exc:
            raise AppError(
                "AUDIO_DURATION_LIMIT",
                f"File vượt giới hạn {max_duration_seconds:g} giây hiện tại. "
                "Hãy dùng bản ghi ngắn hơn trước khi hệ thống hỗ trợ xử lý dài.",
                422,
            ) from exc
    return asdict(metadata)
