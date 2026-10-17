"""Probe container metadata without importing any inference runtime."""

import json
import shutil
import subprocess

from meeting_backend.core.errors import AppError


def probe_audio(path):
    binary = shutil.which("ffprobe")
    if not binary:
        raise AppError("FFPROBE_MISSING", "Cần FFmpeg/ffprobe để kiểm tra file âm thanh.", 503)
    try:
        result = subprocess.run(
            [
                binary,
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=codec_type,sample_rate,channels",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        data = json.loads(result.stdout)
        stream = next(s for s in data.get("streams", []) if s.get("codec_type") == "audio")
        if result.returncode:
            raise ValueError("Invalid container")
        duration = data.get("format", {}).get("duration")
        return {
            "duration_sec": float(duration) if duration else None,
            "sample_rate": int(stream.get("sample_rate") or 0),
            "channels": int(stream.get("channels") or 0),
        }
    except (ValueError, StopIteration, subprocess.TimeoutExpired) as exc:
        raise AppError(
            "INVALID_AUDIO",
            "Không đọc được luồng âm thanh. Hãy kiểm tra file bằng trình phát "
            "hoặc xuất lại WAV/MP3.",
            422,
        ) from exc
