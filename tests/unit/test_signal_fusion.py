from shutil import which

import numpy as np
import pytest

from meeting_pipeline.audio.signal_fusion import afftdn


@pytest.mark.skipif(which("ffmpeg") is None, reason="FFmpeg is required")
def test_afftdn_preserves_timeline_and_samples_near_tail() -> None:
    waveform = np.zeros(18097, dtype=np.float32)
    impulse_positions = [401, len(waveform) - 21]
    waveform[impulse_positions] = 0.7
    filtered = afftdn(waveform, sample_rate=16000)
    assert filtered.shape == waveform.shape
    assert np.sort(np.argpartition(np.abs(filtered), -2)[-2:]).tolist() == impulse_positions
