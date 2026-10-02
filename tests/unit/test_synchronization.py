import numpy as np
import pytest

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
