"""Manifest-driven dataset fetch orchestration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
from huggingface_hub import hf_hub_url

from meeting_pipeline.datasets.download import download_file
from meeting_pipeline.datasets.manifests import DatasetManifest
from meeting_pipeline.datasets.remote_zip import fetch_remote_zip_entries


def fetch_manifest(
    manifest_path: Path, destination_root: Path, token: str | None
) -> dict[str, object]:
    """Fetch one checked manifest without allowing it to exceed its source budget."""
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    dataset_id = str(raw["dataset_id"])
    budget = int(raw["source_budget_bytes"])
    if dataset_id == "libriwasn":
        return _fetch_libriwasn(raw, destination_root, budget)
    manifest = DatasetManifest.model_validate(raw)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    client = httpx.Client(headers=headers, timeout=None, follow_redirects=True)
    received = 0
    files: list[dict[str, object]] = []
    for item in manifest.files:
        url = _resolve_url(item.url)
        destination = destination_root / item.relative_path
        count, sha256 = download_file(
            client,
            url,
            destination,
            budget - received,
            expected_sha256=item.sha256,
            expected_bytes=item.expected_bytes,
        )
        received += count
        _verify_source_checksum(destination, item.source_checksum)
        files.append({"path": item.relative_path, "bytes": count, "sha256": sha256})
    return {"dataset_id": dataset_id, "received_bytes": received, "files": files}


def _resolve_url(url: str) -> str:
    if not url.startswith("hf://datasets/"):
        return url
    spec = url.removeprefix("hf://datasets/")
    repository_and_revision, filename = spec.split("/data/", 1)
    repository, revision = repository_and_revision.split("@", 1)
    return hf_hub_url(repository, f"data/{filename}", repo_type="dataset", revision=revision)


def _fetch_libriwasn(raw: dict[str, object], root: Path, budget: int) -> dict[str, object]:
    archive = raw["archive"]
    if not isinstance(archive, dict) or not isinstance(raw["entries"], list):
        raise ValueError("Invalid LibriWASN manifest")
    checksums, received = fetch_remote_zip_entries(
        httpx.Client(timeout=120, follow_redirects=True),
        str(archive["url"]),
        [str(name) for name in raw["entries"]],
        root / "libriwasn",
        budget,
    )
    return {"dataset_id": "libriwasn", "received_bytes": received, "files": checksums}


def _verify_source_checksum(path: Path, checksum: str | None) -> None:
    if checksum is None:
        return
    algorithm, expected = checksum.split(":", 1)
    if algorithm not in {"md5", "sha256"}:
        raise ValueError(f"Unsupported checksum algorithm: {algorithm}")
    digest = hashlib.new(algorithm)
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        path.unlink(missing_ok=True)
        raise ValueError(f"Checksum mismatch for {path.name}")
