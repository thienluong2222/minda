from meeting_pipeline.datasets.remote_zip import TransferCounter
from meeting_pipeline.domain.errors import DataBudgetExceededError


def test_transfer_counter_counts_retries_and_rejects_over_budget() -> None:
    counter = TransferCounter(10)
    counter.add(6)
    try:
        counter.add(5)
    except DataBudgetExceededError:
        pass
    else:
        raise AssertionError("Budget overrun was not rejected")
    assert counter.received_bytes == 11
