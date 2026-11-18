import numpy as np
import pytest

from meeting_pipeline.audio.synchronization import synchronize_multi_source_audio
from meeting_pipeline.pipeline.stages.synchronize import estimate_offset


def varying_signal(seconds, sample_rate=1000):
    rng = np.random.default_rng(27102026)
    envelope = np.repeat(rng.uniform(0.05, 0.8, seconds * 10), sample_rate // 10)
    return (rng.normal(size=seconds * sample_rate) * envelope).astype(np.float32)


def test_source_event_one_second_late_requires_negative_offset() -> None:
    sample_rate = 16000
    rng = np.random.default_rng(20260916)
    carrier = rng.normal(size=sample_rate * 3).astype(np.float32)
    modulation = np.repeat(rng.uniform(0.1, 1.0, size=30), sample_rate // 10)
    event = carrier * modulation
    reference = np.concatenate([event, np.zeros(sample_rate, dtype=np.float32)])
    source = np.concatenate([np.zeros(sample_rate, dtype=np.float32), event])
    result = estimate_offset(reference, source, sample_rate, max_offset_seconds=2)
    assert result.mapping.offset_sec == pytest.approx(-1.0, abs=0.02)


def test_coverage_is_recorded_before_tail_zero_padding() -> None:
    reference = np.ones(16000 * 2, dtype=np.float32) * 0.1
    short = np.zeros(16000, dtype=np.float32)
    aligned, metadata, _ = synchronize_multi_source_audio(
        {"reference": reference, "short": short}, reference_source_id="reference"
    )
    assert len(aligned["short"]) == len(aligned["reference"])
    assert metadata["reference"]["status"] == "reference"
    assert metadata["short"]["valid_coverage_interval"][1] == pytest.approx(1.0)
    assert metadata["short"]["status"] == "alignment_failed"


def test_earlier_source_keeps_unique_head_and_shifts_reference():
    original = varying_signal(13)
    reference = original[3000:]
    aligned, metadata, _ = synchronize_multi_source_audio(
        {"reference": reference, "early": original},
        sample_rate=1000,
        reference_source_id="reference",
    )
    assert metadata["early"]["offset_sec"] == pytest.approx(-3, abs=0.01)
    assert metadata["reference"]["origin_shift_sec"] == pytest.approx(3, abs=0.01)
    np.testing.assert_array_equal(aligned["early"], original)
    np.testing.assert_array_equal(aligned["reference"][3000:], reference)
    assert metadata["early"]["valid_coverage_interval"] == [0, 13]
    assert metadata["reference"]["valid_coverage_interval"] == [3, 13]


def test_late_source_uses_configured_search_and_corresponding_drift_windows():
    reference = varying_signal(100)
    _, metadata, _ = synchronize_multi_source_audio(
        {"reference": reference, "late": reference[45000:]},
        sample_rate=1000,
        reference_source_id="reference",
        max_offset_seconds=120,
        fine_window_seconds=4,
        long_recording_step_seconds=10,
    )
    assert metadata["late"]["offset_sec"] == pytest.approx(45, abs=0.02)
    assert metadata["late"]["status"] == "aligned"
    assert abs(metadata["late"]["drift_ppm"]) < 1
    _, limited, _ = synchronize_multi_source_audio(
        {"reference": reference, "late": reference[45000:]},
        sample_rate=1000,
        reference_source_id="reference",
        max_offset_seconds=10,
    )
    assert limited["late"]["status"] == "alignment_failed"


@pytest.mark.parametrize(
    "drift, expected",
    [
        ((0.0, 5.0, "drift_unresolved"), "drift_unresolved"),
        ((0.0, 0.5, "aligned"), "aligned"),
    ],
)
def test_zero_drift_does_not_hide_estimation_status(monkeypatch, drift, expected):
    import meeting_pipeline.audio.synchronization as module

    monkeypatch.setattr(module, "_estimate_windowed_drift", lambda *a, **kw: drift)
    signal = varying_signal(10)
    _, metadata, _ = synchronize_multi_source_audio(
        {"reference": signal, "other": signal.copy()},
        sample_rate=1000,
        reference_source_id="reference",
    )
    assert metadata["other"]["status"] == expected
    if expected == "drift_unresolved":
        assert metadata["other"]["drift_residual_ms"] is None
        assert metadata["other"]["residual_ms"] > 20


def test_short_recording_does_not_prove_zero_drift():
    signal = varying_signal(2)
    _, metadata, _ = synchronize_multi_source_audio(
        {"reference": signal, "other": signal.copy()},
        sample_rate=1000,
        reference_source_id="reference",
    )
    assert metadata["other"]["status"] == "drift_unresolved"
