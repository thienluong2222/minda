"""Lazy model registry and explicit download preparation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download

from meeting_pipeline.domain.errors import ModelUnavailableError


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """Pinned logical model entry and access requirements."""

    role: str
    model_id: str
    revision: str
    gated: bool = False


def configured_models(config: dict[str, dict[str, object]]) -> tuple[ModelSpec, ...]:
    """Build registry entries from validated stage configuration."""
    return (
        ModelSpec(
            "segmentation",
            str(config["models"]["segmentation_id"]),
            str(config["models"]["segmentation_revision"]),
            True,
        ),
        ModelSpec(
            "embedding",
            str(config["identity"]["model_id"]),
            str(config["identity"]["model_revision"]),
        ),
        ModelSpec(
            "separation",
            str(config["separation"]["model_id"]),
            str(config["separation"]["model_revision"]),
        ),
        ModelSpec("asr", str(config["asr"]["model_id"]), str(config["asr"]["model_revision"])),
    )


def prepare_model(spec: ModelSpec, cache_dir: Path) -> Path:
    """Download one explicit model snapshot; gated models require user-owned token."""
    token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_HUB_TOKEN")
    if spec.gated and not token:
        raise ModelUnavailableError(
            f"{spec.model_id} requires HF_TOKEN and accepted Hugging Face terms"
        )
    try:
        local_path = snapshot_download(
            repo_id=spec.model_id,
            revision=spec.revision,
            cache_dir=cache_dir,
            token=token,
        )
    except Exception as exc:
        raise ModelUnavailableError(f"Cannot prepare {spec.model_id}: {exc}") from exc
    return Path(local_path)


def model_download_size(spec: ModelSpec) -> int | None:
    """Return the repository's known file bytes; inaccessible metadata remains unknown."""
    token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_HUB_TOKEN")
    try:
        info = HfApi().model_info(
            spec.model_id, revision=spec.revision, files_metadata=True, token=token
        )
    except Exception:
        return None
    sizes = [sibling.size for sibling in (info.siblings or []) if sibling.size is not None]
    return sum(sizes) if sizes else None
