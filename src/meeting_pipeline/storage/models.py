"""Normalized metadata tables required by the version-one contract."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from meeting_pipeline.storage.database import Base


def utc_now() -> datetime:
    """Return an aware UTC timestamp for persisted lifecycle fields."""
    return datetime.now(UTC)


class Speaker(Base):
    __tablename__ = "speakers"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class EnrollmentSample(Base):
    __tablename__ = "enrollment_samples"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    speaker_id: Mapped[str] = mapped_column(ForeignKey("speakers.id"))
    artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id"))
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    valid_speech_seconds: Mapped[float | None] = mapped_column(Float)
    sha256: Mapped[str] = mapped_column(String(64))


class SpeakerProfile(Base):
    __tablename__ = "speaker_profiles"
    __table_args__ = (UniqueConstraint("speaker_id", "version"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    speaker_id: Mapped[str] = mapped_column(ForeignKey("speakers.id"))
    version: Mapped[int] = mapped_column(Integer)
    model_id: Mapped[str] = mapped_column(String)
    model_revision: Mapped[str] = mapped_column(String)
    support_sample_ids: Mapped[list[str]] = mapped_column(JSON)
    embedding_artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id"))
    preprocessing_hash: Mapped[str] = mapped_column(String(64))


class Meeting(Base):
    __tablename__ = "meetings"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MeetingParticipant(Base):
    __tablename__ = "meeting_participants"
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id"), primary_key=True)
    speaker_id: Mapped[str] = mapped_column(ForeignKey("speakers.id"), primary_key=True)
    profile_version: Mapped[int] = mapped_column(Integer)


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    relative_path: Mapped[str] = mapped_column(String, unique=True)
    media_type: Mapped[str] = mapped_column(String)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("meeting_id", "sha256"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id"))
    original_name: Mapped[str] = mapped_column(String)
    original_artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id"))
    sha256: Mapped[str] = mapped_column(String(64))
    sample_rate: Mapped[int] = mapped_column(Integer)
    channels: Mapped[int] = mapped_column(Integer)
    sample_count: Mapped[int] = mapped_column(Integer)
    device_label: Mapped[str | None] = mapped_column(String(200))
    near_speaker_id: Mapped[str | None] = mapped_column(ForeignKey("speakers.id"))


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (UniqueConstraint("meeting_id", "idempotency_key"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id"))
    status: Mapped[str] = mapped_column(String(20), index=True)
    stage: Mapped[str | None] = mapped_column(String(40))
    progress_done: Mapped[int | None] = mapped_column(Integer)
    progress_total: Mapped[int | None] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    config_snapshot: Mapped[dict[str, object]] = mapped_column(JSON)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    worker_id: Mapped[str | None] = mapped_column(String)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
