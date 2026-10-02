"""Content-addressed artifact publication under a configured local root."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    """Metadata published only after an atomic file replacement."""

    relative_path: str
    sha256: str
    size_bytes: int


class ArtifactStore:
    """Resolve IDs in metadata to files without accepting arbitrary URL paths."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def write_stream(self, relative_path: Path, source: BinaryIO) -> StoredArtifact:
        """Write bounded chunks to a sibling temp file, fsync, then atomically publish."""
        destination = self._resolve(relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        descriptor, temporary_name = tempfile.mkstemp(dir=destination.parent, prefix=".artifact-")
        try:
            with os.fdopen(descriptor, "wb") as target:
                while chunk := source.read(1024 * 1024):
                    target.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
                target.flush()
                os.fsync(target.fileno())
            Path(temporary_name).replace(destination)
        except BaseException:
            Path(temporary_name).unlink(missing_ok=True)
            raise
        return StoredArtifact(str(relative_path), digest.hexdigest(), size)

    def path(self, relative_path: Path) -> Path:
        """Resolve a metadata-owned relative path and reject root escape."""
        return self._resolve(relative_path)

    def _resolve(self, relative_path: Path) -> Path:
        if relative_path.is_absolute():
            raise ValueError("Artifact paths must be relative")
        resolved = (self.root / relative_path).resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError("Artifact path escapes configured root")
        return resolved
