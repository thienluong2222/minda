from io import BytesIO
from pathlib import Path

import pytest

from meeting_pipeline.storage.artifact_store import ArtifactStore


def test_artifact_write_is_hashed_and_rejects_escape(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    artifact = store.write_stream(Path("runs/a/output.bin"), BytesIO(b"complete"))
    assert artifact.size_bytes == 8
    assert store.path(Path(artifact.relative_path)).read_bytes() == b"complete"
    with pytest.raises(ValueError):
        store.path(Path("../outside"))
