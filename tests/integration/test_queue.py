from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import update

from meeting_pipeline.domain.schemas import RunStatus
from meeting_pipeline.storage.database import (
    create_sqlite_engine,
    initialize_database,
    session_factory,
)
from meeting_pipeline.storage.models import Meeting, Run
from meeting_pipeline.worker.queue import RunQueue


def test_claim_and_expired_lease_becomes_interrupted(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "app.sqlite")
    initialize_database(engine)
    sessions = session_factory(engine)
    with sessions.begin() as session:
        session.add(Meeting(id="m", name="Meeting"))
        session.add(
            Run(
                id="r",
                meeting_id="m",
                status=RunStatus.QUEUED.value,
                idempotency_key="once",
                config_snapshot={},
                warnings=[],
            )
        )
    queue = RunQueue(sessions, lease_seconds=1)
    assert queue.claim_next("worker") == "r"
    with sessions.begin() as session:
        session.execute(
            update(Run)
            .where(Run.id == "r")
            .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    assert queue.interrupt_expired() == 1
    with sessions() as session:
        assert session.get(Run, "r").status == RunStatus.INTERRUPTED.value
