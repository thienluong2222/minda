"""Dataset transfer plans with explicit unknown sizes and byte budgets."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DatasetFile(BaseModel):
    """One remote object planned for transfer; null size is not treated as zero."""

    url: str
    relative_path: str
    expected_bytes: int | None = Field(default=None, gt=0)
    sha256: str | None = None
    source_checksum: str | None = None
    etag: str | None = None
    split: str
    session_id: str | None = None
    speaker_id: str | None = None
    channel_id: str | None = None


class DatasetManifest(BaseModel):
    """Versioned source, license and transfer selection metadata."""

    schema_version: str = "1.0"
    dataset_id: str
    source_version: str
    license_name: str
    license_url: str
    source_budget_bytes: int = Field(gt=0)
    files: list[DatasetFile]

    @property
    def planned_known_bytes(self) -> int:
        """Return known planned bytes without masking unknown entries."""
        return sum(item.expected_bytes or 0 for item in self.files)

    @property
    def unknown_size_count(self) -> int:
        """Count remote objects whose transfer size needs preflight."""
        return sum(item.expected_bytes is None for item in self.files)
