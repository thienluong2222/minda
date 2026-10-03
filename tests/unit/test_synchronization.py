import numpy as np
import pytest

from meeting_pipeline.audio.synchronization import synchronize_multi_source_audio
from meeting_pipeline.pipeline.stages.synchronize import estimate_offset


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
