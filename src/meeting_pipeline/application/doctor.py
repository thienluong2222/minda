"""Read-only environment diagnostics; never downloads implicitly."""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from meeting_pipeline.config import PipelineConfig
from meeting_pipeline.storage.database import create_sqlite_engine, initialize_database


@dataclass(frozen=True, slots=True)
class CheckResult:
    """One diagnostic with a stable name and actionable detail."""

    name: str
    ok: bool
    detail: str


def run_checks(config: PipelineConfig) -> list[CheckResult]:
    """Check runtime, executables, writable storage, DB and model credentials."""
    results = [
        CheckResult(
            "python",
            sys.version_info[:2] == (3, 11),
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        ),
        CheckResult(
            "ffmpeg", shutil.which("ffmpeg") is not None, shutil.which("ffmpeg") or "missing"
        ),
        CheckResult(
            "ffprobe", shutil.which("ffprobe") is not None, shutil.which("ffprobe") or "missing"
        ),
    ]
    data_dir = config.paths.data_dir
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        marker = data_dir / ".write-check"
        marker.write_bytes(b"")
        marker.unlink()
        results.append(CheckResult("data_dir", True, str(data_dir.resolve())))
    except OSError as exc:
        results.append(CheckResult("data_dir", False, str(exc)))
    try:
        config.paths.database_path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_sqlite_engine(config.paths.database_path)
        initialize_database(engine)
        engine.dispose()
        results.append(CheckResult("sqlite", True, str(config.paths.database_path.resolve())))
    except Exception as exc:
        results.append(CheckResult("sqlite", False, str(exc)))
    for module in ("torch", "torchaudio", "speechbrain", "pyannote.audio", "transformers"):
        results.append(
            CheckResult(
                f"module:{module}",
                importlib.util.find_spec(module) is not None,
                "installed" if importlib.util.find_spec(module) else "missing",
            )
        )
    token_present = bool(os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_HUB_TOKEN"))
    results.append(
        CheckResult(
            "pyannote_access",
            token_present
            or _snapshot_exists(
                config.paths.model_cache_dir,
                "pyannote/segmentation-3.0",
                str(config.models["segmentation_revision"]),
            ),
            "token set or exact snapshot cached"
            if token_present
            else "set HF_TOKEN after accepting model terms",
        )
    )
    return results


def _snapshot_exists(cache_dir: Path, model_id: str, revision: str) -> bool:
    """Check an exact cached snapshot without network access."""
    repository = "models--" + model_id.replace("/", "--")
    return (cache_dir / repository / "snapshots" / revision).is_dir()
