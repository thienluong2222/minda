"""SQLite engine configuration for short transactional metadata operations."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Base for metadata tables; waveforms remain in the artifact store."""


def create_sqlite_engine(path: Path) -> Engine:
    """Create a local SQLite engine with required safety/concurrency pragmas."""
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}", future=True)

    @event.listens_for(engine, "connect")
    def set_pragmas(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return engine


def session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return sessions that expire objects after each committed transaction."""
    return sessionmaker(bind=engine, expire_on_commit=True)


def initialize_database(engine: Engine) -> None:
    """Create the current M1 schema for a fresh local database."""
    from meeting_pipeline.storage import models  # noqa: F401

    Base.metadata.create_all(engine)
