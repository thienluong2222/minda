import numpy as np

from meeting_pipeline.pipeline.prototype import _peak_limit


def test_peak_limit_only_attenuates_out_of_range_audio() -> None:
    waveform = np.asarray([-2.0, 0.0, 1.0], dtype=np.float32)
    processed, gain = _peak_limit(waveform)
    assert gain == 0.475
    assert np.max(np.abs(processed)) <= 0.95


def test_peak_limit_does_not_boost_quiet_audio() -> None:
    waveform = np.asarray([-0.2, 0.1], dtype=np.float32)
    processed, gain = _peak_limit(waveform)
    assert gain == 1.0
    np.testing.assert_array_equal(processed, waveform)
