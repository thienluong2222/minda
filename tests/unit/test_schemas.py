import pytest
from pydantic import ValidationError

from meeting_pipeline.domain.schemas import Interval


def test_interval_is_half_open_and_non_empty() -> None:
    assert Interval(start_sec=0, end_sec=1).end_sec == 1
    with pytest.raises(ValidationError):
        Interval(start_sec=1, end_sec=1)
