"""Safe FFmpeg/ffprobe based audio ingest."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from meeting_pipeline.domain.errors import InvalidAudioError


@dataclass(frozen=True, slots=True)
class AudioMetadata:
    """Decoded stream metadata verified by ffprobe."""

    codec_name: str
    sample_rate: int
    channels: int
    duration_sec: float


def sha256_file(path: Path, chunk_bytes: int = 1024 * 1024) -> str:
    """Hash a file incrementally so uploads do not need to fit in memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_bytes):
            digest.update(chunk)
    return digest.hexdigest()


def probe_audio(path: Path, timeout_sec: float = 30) -> AudioMetadata:
    """Read the first audio stream without interpolating the user-provided filename."""
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_name,sample_rate,channels,duration",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, check=True, timeout=timeout_sec)
        stream = json.loads(result.stdout)["streams"][0]
        return AudioMetadata(
            codec_name=str(stream["codec_name"]),
            sample_rate=int(stream["sample_rate"]),
            channels=int(stream["channels"]),
            duration_sec=float(stream["duration"]),
        )
    except (
        subprocess.SubprocessError,
        KeyError,
        IndexError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise InvalidAudioError(f"Cannot probe audio: {path.name}") from exc


def decode_mono(path: Path, output_path: Path, sample_rate: int = 16000) -> int:
    """Decode fully to mono float WAV and return the verified output sample count."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".part.wav")
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-nostdin",
        "-y",
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-c:a",
        "pcm_f32le",
        str(temporary),
    ]
    try:
        subprocess.run(command, capture_output=True, check=True, timeout=3600)
        info = sf.info(temporary)
        if info.frames <= 0 or info.samplerate != sample_rate or info.channels != 1:
            raise InvalidAudioError(f"Decoded audio has invalid shape: {path.name}")
        temporary.replace(output_path)
        return int(info.frames)
    except subprocess.SubprocessError as exc:
        temporary.unlink(missing_ok=True)
        raise InvalidAudioError(f"Cannot decode audio: {path.name}") from exc


def audio_level_features(path: Path, block_frames: int = 65536) -> dict[str, float]:
    """Measure pre-normalization mono WAV level features using bounded memory."""
    squares = 0.0
    sample_count = 0
    peak = 0.0
    near_full_scale = 0
    sample_sum = 0.0
    with sf.SoundFile(path) as stream:
        for block in stream.blocks(blocksize=block_frames, dtype="float32", always_2d=False):
            values = np.asarray(block, dtype=np.float64)
            squares += float(np.dot(values, values))
            sample_sum += float(values.sum())
            sample_count += values.size
            peak = max(peak, float(np.max(np.abs(values), initial=0)))
            near_full_scale += int(np.count_nonzero(np.abs(values) >= 0.999))
    if sample_count == 0:
        raise InvalidAudioError(f"Decoded audio is empty: {path.name}")
    return {
        "rms": float(np.sqrt(squares / sample_count)),
        "peak": peak,
        "near_full_scale_ratio": near_full_scale / sample_count,
        "dc_offset": sample_sum / sample_count,
    }
