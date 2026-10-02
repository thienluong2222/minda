"""Transactional SQLite job claiming and lifecycle transitions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import Select, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from meeting_pipeline.domain.schemas import RunStatus
from meeting_pipeline.storage.models import Run


class RunQueue:
    """Single-worker queue; inference always happens outside DB transactions."""

    def __init__(self, sessions: sessionmaker[Session], lease_seconds: int = 60) -> None:
        self.sessions = sessions
        self.lease_seconds = lease_seconds

    def claim_next(self, worker_id: str) -> str | None:
        """Atomically claim the oldest queued run and return its ID."""
        now = datetime.now(UTC)
        with self.sessions.begin() as session:
            query: Select[tuple[Run]] = (
                select(Run)
                .where(Run.status == RunStatus.QUEUED.value)
                .order_by(Run.created_at)
                .limit(1)
            )
            run = session.scalar(query)
            if run is None:
                return None
            changed = cast(
                CursorResult[Any],
                session.execute(
                    update(Run)
                    .where(Run.id == run.id, Run.status == RunStatus.QUEUED.value)
                    .values(
                        status=RunStatus.RUNNING.value,
                        worker_id=worker_id,
                        started_at=now,
                        heartbeat_at=now,
                        lease_expires_at=now + timedelta(seconds=self.lease_seconds),
                    )
                ),
            ).rowcount
            return run.id if changed == 1 else None

    def heartbeat(self, run_id: str, worker_id: str) -> None:
        """Extend a running job lease without holding a long inference transaction."""
        now = datetime.now(UTC)
        with self.sessions.begin() as session:
            session.execute(
                update(Run)
                .where(
                    Run.id == run_id,
                    Run.worker_id == worker_id,
                    Run.status == RunStatus.RUNNING.value,
                )
                .values(
                    heartbeat_at=now, lease_expires_at=now + timedelta(seconds=self.lease_seconds)
                )
            )

    def interrupt_expired(self) -> int:
        """Mark lost worker leases interrupted so they are never reported successful."""
        now = datetime.now(UTC)
        with self.sessions.begin() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(Run)
                    .where(Run.status == RunStatus.RUNNING.value, Run.lease_expires_at < now)
                    .values(
                        status=RunStatus.INTERRUPTED.value,
                        completed_at=now,
                        error_code="WORKER_LOST",
                    )
                ),
            )
            return int(result.rowcount or 0)

    def request_cancel(self, run_id: str) -> bool:
        """Set cooperative cancellation; stages inspect it between chunks."""
        with self.sessions.begin() as session:
            result = cast(
                CursorResult[Any],
                session.execute(update(Run).where(Run.id == run_id).values(cancel_requested=True)),
            )
            return bool(result.rowcount == 1)
