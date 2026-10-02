"""Read selected ZIP entries over HTTP Range without downloading full archives."""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

import httpx

from meeting_pipeline.domain.errors import DataBudgetBlockedError, DataBudgetExceededError

_CONTENT_RANGE = re.compile(r"bytes (\d+)-(\d+)/(\d+)")


@dataclass(slots=True)
class TransferCounter:
    """Count every response byte against one source network budget."""

    budget_bytes: int
    received_bytes: int = 0

    def add(self, amount: int) -> None:
        """Add actual bytes and reject the transfer before publishing artifacts."""
        self.received_bytes += amount
        if self.received_bytes > self.budget_bytes:
            raise DataBudgetExceededError(
                f"Received {self.received_bytes} bytes, budget is {self.budget_bytes}"
            )


class HttpRangeReader(io.RawIOBase):
    """Seekable read-only view of one remote object backed by exact Range requests."""

    def __init__(self, client: httpx.Client, url: str, counter: TransferCounter) -> None:
        self.client = client
        self.url = url
        self.counter = counter
        self.position = 0
        response = client.get(url, headers={"Range": "bytes=0-0"}, follow_redirects=True)
        self.counter.add(len(response.content))
        match = _CONTENT_RANGE.fullmatch(response.headers.get("content-range", ""))
        if response.status_code != 206 or match is None:
            raise DataBudgetBlockedError("Server does not provide bounded HTTP Range responses")
        self.length = int(match.group(3))

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.position

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            position = offset
        elif whence == io.SEEK_CUR:
            position = self.position + offset
        elif whence == io.SEEK_END:
            position = self.length + offset
        else:
            raise ValueError("Unsupported seek mode")
        if position < 0:
            raise ValueError("Cannot seek before byte zero")
        self.position = min(position, self.length)
        return self.position

    def read(self, size: int = -1) -> bytes:
        if self.position >= self.length:
            return b""
        end = self.length - 1 if size < 0 else min(self.length - 1, self.position + size - 1)
        if end < self.position:
            return b""
        response = self.client.get(
            self.url,
            headers={"Range": f"bytes={self.position}-{end}"},
            follow_redirects=True,
        )
        body = response.content
        self.counter.add(len(body))
        match = _CONTENT_RANGE.fullmatch(response.headers.get("content-range", ""))
        if response.status_code != 206 or match is None:
            raise DataBudgetBlockedError("Server ignored a bounded ZIP range request")
        actual_start, actual_end = int(match.group(1)), int(match.group(2))
        if actual_start != self.position or actual_end > end:
            raise DataBudgetBlockedError("Server returned bytes outside the requested ZIP range")
        self.position += len(body)
        return body


def inspect_remote_zip(
    client: httpx.Client, url: str, budget_bytes: int
) -> tuple[list[zipfile.ZipInfo], int]:
    """Return central-directory entries and the exact metadata transfer cost."""
    counter = TransferCounter(budget_bytes)
    reader = HttpRangeReader(client, url, counter)
    with zipfile.ZipFile(reader) as archive:
        entries = archive.infolist()
    return entries, counter.received_bytes


def fetch_remote_zip_entries(
    client: httpx.Client,
    url: str,
    entry_names: list[str],
    destination_dir: Path,
    budget_bytes: int,
) -> tuple[dict[str, str], int]:
    """Extract named entries atomically while counting all HTTP response bytes."""
    counter = TransferCounter(budget_bytes)
    reader = HttpRangeReader(client, url, counter)
    checksums: dict[str, str] = {}
    with zipfile.ZipFile(reader) as archive:
        available = {entry.filename for entry in archive.infolist()}
        missing = sorted(set(entry_names) - available)
        if missing:
            raise KeyError(f"ZIP entries not found: {missing}")
        for name in entry_names:
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"Unsafe ZIP entry path: {name}")
            output = destination_dir / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            temporary = output.with_suffix(output.suffix + ".part")
            digest = hashlib.sha256()
            try:
                with archive.open(name) as source, temporary.open("wb") as target:
                    while chunk := source.read(1024 * 1024):
                        target.write(chunk)
                        digest.update(chunk)
                temporary.replace(output)
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
            checksums[name] = digest.hexdigest()
    return checksums, counter.received_bytes
