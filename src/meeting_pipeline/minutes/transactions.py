"""One lock and rollback boundary for edits affecting transcript and document artifacts."""

from __future__ import annotations

import shutil
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from meeting_pipeline.minutes.model_runtime import ModelRuntimeError

GENERATION_LOCK = threading.Lock()


@contextmanager
def minutes_transaction(run_dir: Path) -> Iterator[None]:
    """Reject busy edits before their first write; restore the complete edited state on failure."""
    if not GENERATION_LOCK.acquire(blocking=False):
        raise ModelRuntimeError("Một biên bản đang được tạo. Hãy thử lại khi hoàn thành.")
    names = ["template", "minutes", "exports", "timeline.json", "speaker_labels.json"]
    try:
        with tempfile.TemporaryDirectory(prefix=".minutes-edit-", dir=run_dir) as temp:
            backup = Path(temp)
            for name in names:
                src, dst = run_dir / name, backup / name
                if src.is_dir():
                    shutil.copytree(src, dst)
                elif src.is_file():
                    shutil.copy2(src, dst)
            try:
                yield
            except BaseException:
                for name in names:
                    dst, src = run_dir / name, backup / name
                    if dst.is_dir():
                        shutil.rmtree(dst)
                    elif dst.is_file():
                        dst.unlink()
                    if src.is_dir():
                        shutil.copytree(src, dst)
                    elif src.is_file():
                        shutil.copy2(src, dst)
                raise
    finally:
        GENERATION_LOCK.release()
