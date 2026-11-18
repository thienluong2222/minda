"""API and worker ingest must agree on playable files and duration limits."""

import json
import shutil
import subprocess
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

from meeting_backend.infrastructure.artifacts.media import probe_audio as api_probe
from meeting_pipeline.adapters.audio_io import AudioMetadata, probe_audio, validate_audio_duration
from meeting_pipeline.domain.errors import InvalidAudioError


def test_webm_with_container_duration_is_accepted_identically(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg is required")
    wav, webm = tmp_path / "input.wav", tmp_path / "recording.webm"
    sf.write(wav, np.zeros(16000, dtype=np.float32), 16000)
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(wav),
            "-c:a",
            "libopus",
            str(webm),
        ],
        check=True,
        capture_output=True,
    )
    core = probe_audio(webm)
    api = api_probe(webm, max_duration_seconds=1200)
    assert core.duration_sec == api["duration_sec"]
    assert api["codec_name"] == "opus"
    assert api["duration_source"] == "container"
    assert api["duration_is_estimate"] is True
    assert 1 <= core.duration_sec < 1.1


@pytest.mark.parametrize("duration", ["NaN", "inf", "0", "-1", "N/A", None])
def test_invalid_or_missing_duration_is_not_accepted(monkeypatch, tmp_path, duration):
    import meeting_pipeline.adapters.audio_io as module

    data = {
        "streams": [
            {
                "codec_name": "pcm_s16le",
                "sample_rate": "16000",
                "channels": 1,
                "duration": duration,
            }
        ],
        "format": {"duration": duration},
    }
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(
            stdout=json.dumps(data).encode(),
        ),
    )
    with pytest.raises(InvalidAudioError):
        probe_audio(tmp_path / "bad.wav")


def test_shared_duration_limit_accepts_boundary_and_rejects_excess():
    from pathlib import Path

    from meeting_pipeline.config import load_config

    limit = load_config(Path("configs/default.yaml")).audio.max_duration_seconds
    validate_audio_duration(AudioMetadata("pcm_s16le", 16000, 1, 7200), limit)
    with pytest.raises(InvalidAudioError):
        validate_audio_duration(AudioMetadata("pcm_s16le", 16000, 1, 7200 + 1 / 16000), limit)
