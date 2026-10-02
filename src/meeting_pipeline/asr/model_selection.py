"""Resolve pinned, offline ASR checkpoints without loading model weights."""

from __future__ import annotations

import re
from pathlib import Path

from meeting_pipeline.config import AsrConfig
from meeting_pipeline.domain.errors import ModelUnavailableError


def resolve_model_snapshot(config: AsrConfig, cache_dir: Path) -> Path:
    """Return a local snapshot for the exact selected revision or fail explicitly."""
    if not re.fullmatch(r"[0-9a-f]{40}", config.model_revision):
        raise ValueError("ASR model_revision must be a full 40-character commit SHA")
    snapshot = (
        cache_dir
        / f"models--{config.model_id.replace('/', '--')}"
        / "snapshots"
        / config.model_revision
    )
    if not snapshot.is_dir():
        raise ModelUnavailableError(
            f"Missing ASR snapshot: {config.model_id}@{config.model_revision}; "
            "download this pinned revision before running the job"
        )
    return snapshot
