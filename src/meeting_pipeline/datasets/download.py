"""Budget-enforcing streamed downloads with atomic publication."""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx

from meeting_pipeline.domain.errors import DataBudgetExceededError


def download_file(
    client: httpx.Client,
    url: str,
    destination: Path,
    remaining_budget_bytes: int,
    expected_sha256: str | None = None,
    expected_bytes: int | None = None,
) -> tuple[int, str]:
    """Stream a remote object, counting actual bytes and publishing atomically."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    received = 0
    digest = hashlib.sha256()
    try:
        temporary.unlink(missing_ok=True)
        with client.stream("GET", url, follow_redirects=True) as response:
            response.raise_for_status()
            with temporary.open("wb") as stream:
                for chunk in response.iter_bytes():
                    received += len(chunk)
                    if received > remaining_budget_bytes:
                        raise DataBudgetExceededError(
                            f"Transfer exceeded remaining budget at {received} bytes"
                        )
                    digest.update(chunk)
                    stream.write(chunk)
        checksum = digest.hexdigest()
        if expected_bytes is not None and received != expected_bytes:
            raise ValueError(f"Expected {expected_bytes} bytes but received {received}")
        if expected_sha256 is not None and checksum != expected_sha256:
            raise ValueError("Downloaded checksum does not match manifest")
        temporary.replace(destination)
        return received, checksum
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
