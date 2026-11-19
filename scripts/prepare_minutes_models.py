"""Explicitly download pinned LLM, embedding, and LoRA B inference weights once.

Runtime inference itself always stays offline and verifies SHA-256 checksums.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import yaml
from huggingface_hub import snapshot_download

DEFAULT_ADAPTER_RELEASE_TAG = "lora-b-v21-ckpt132"
DEFAULT_ADAPTER_ARCHIVE_NAME = f"{DEFAULT_ADAPTER_RELEASE_TAG}.zip"
DEFAULT_ADAPTER_BASE_URL = (
    f"https://github.com/thienluong2222/minda/releases/download/{DEFAULT_ADAPTER_RELEASE_TAG}"
)
DEFAULT_ADAPTER_ARCHIVE_URL = f"{DEFAULT_ADAPTER_BASE_URL}/{DEFAULT_ADAPTER_ARCHIVE_NAME}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_to_temp(url: str, parent_dir: Path) -> Path:
    parent_dir.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {url} ...")
    with tempfile.NamedTemporaryFile(dir=parent_dir, delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        headers = {"User-Agent": "minda-prepare-minutes-models/1.0"}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=300) as response, tmp_path.open("wb") as out:
            shutil.copyfileobj(response, out, length=1 << 20)
        return tmp_path
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _extract_verified_archive(
    archive_path: Path,
    adapter_dir: Path,
    expected_files: list[tuple[str, str | None]],
) -> None:
    adapter_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=adapter_dir) as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        with zipfile.ZipFile(archive_path, "r") as zf:
            members = {Path(name).name: name for name in zf.namelist() if not name.endswith("/")}
            for filename, expected_sha in expected_files:
                if filename not in members:
                    raise ValueError(f"File '{filename}' không tồn tại trong {archive_path.name}.")
                extracted = tmp_dir / filename
                with zf.open(members[filename], "r") as src, extracted.open("wb") as dst:
                    shutil.copyfileobj(src, dst, length=1 << 20)
                actual = _sha256(extracted)
                if expected_sha and actual != expected_sha:
                    raise ValueError(
                        f"SHA-256 mismatch for {filename}: expected {expected_sha}, got {actual}"
                    )
        # Re-open inside the temporary dir context before cleanup is needed; move atomically.
            for filename, _ in expected_files:
                (tmp_dir / filename).replace(adapter_dir / filename)
    print(f"Verified & extracted LoRA B adapter into: {adapter_dir}")


def _download_verified_file(url: str, destination: Path, expected_sha256: str | None) -> None:
    tmp_path = _download_to_temp(url, destination.parent)
    try:
        actual = _sha256(tmp_path)
        if expected_sha256 and actual != expected_sha256:
            raise ValueError(
                f"SHA-256 mismatch for {destination.name}: expected {expected_sha256}, got {actual}"
            )
        tmp_path.replace(destination)
        print(f"Verified & saved: {destination} (sha256={actual[:16]}...)")
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def prepare_adapter(
    root: Path,
    settings: dict,
    *,
    archive_url: str,
    local_archive: Path | None = None,
    check_only: bool = False,
) -> None:
    adapter_rel = settings.get("adapter_path")
    if not adapter_rel:
        print("adapter_path is null in configs/minutes.yaml; skipping LoRA adapter.")
        return

    adapter_dir = (root / adapter_rel).resolve()
    expected_files = [
        ("adapter_config.json", settings.get("adapter_config_sha256")),
        ("adapter_model.safetensors", settings.get("adapter_sha256")),
    ]

    all_verified = all(
        (adapter_dir / name).is_file()
        and (not expected_sha or _sha256(adapter_dir / name) == expected_sha)
        for name, expected_sha in expected_files
    )
    if all_verified:
        print(f"LoRA B adapter ready & verified: {adapter_dir}")
        return

    if check_only:
        raise SystemExit(
            f"Thiếu hoặc sai checksum LoRA B adapter tại {adapter_dir}. "
            f"Chạy lại không có --check-only để tải từ {archive_url}."
        )

    if local_archive is not None:
        _extract_verified_archive(local_archive.resolve(), adapter_dir, expected_files)
        return

    if archive_url.endswith(".zip"):
        tmp_zip = None
        try:
            tmp_zip = _download_to_temp(archive_url, adapter_dir)
            _extract_verified_archive(tmp_zip, adapter_dir, expected_files)
            return
        except urllib.error.HTTPError as exc:
            raise SystemExit(
                f"Không tải được {archive_url} (HTTP {exc.code}).\n"
                f"Hãy đảm bảo GitHub Release tag '{DEFAULT_ADAPTER_RELEASE_TAG}' đã upload file "
                f"'{DEFAULT_ADAPTER_ARCHIVE_NAME}', truyền --adapter-url <URL> hoặc "
                "--adapter-archive <file.zip>, hoặc chạy demo bằng mô hình nền với --skip-adapter "
                "và đặt adapter_path: null trong configs/minutes.yaml."
            ) from exc
        finally:
            if tmp_zip is not None:
                tmp_zip.unlink(missing_ok=True)

    for filename, expected_sha in expected_files:
        url = f"{archive_url.rstrip('/')}/{filename}"
        try:
            _download_verified_file(url, adapter_dir / filename, expected_sha)
        except urllib.error.HTTPError as exc:
            raise SystemExit(
                f"Không tải được {filename} từ {url} (HTTP {exc.code})."
            ) from exc


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download pinned Qwen3-4B, E5-small, and LoRA B inference weights."
    )
    parser.add_argument(
        "--adapter-url",
        default=os.getenv("MINDA_ADAPTER_URL", DEFAULT_ADAPTER_ARCHIVE_URL),
        help="URL to lora-b-v21-ckpt132.zip (or base URL hosting raw adapter files).",
    )
    parser.add_argument(
        "--adapter-archive",
        type=Path,
        default=None,
        help="Optional local path to lora-b-v21-ckpt132.zip for offline installation.",
    )
    parser.add_argument(
        "--skip-adapter",
        action="store_true",
        help="Skip downloading the LoRA B adapter (base model + embedding only).",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Verify local snapshots and adapter checksums without downloading.",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    settings = yaml.safe_load((root / "configs/minutes.yaml").read_text(encoding="utf-8"))

    for prefix in ("model", "embedding"):
        if args.check_only:
            snap = (
                root
                / settings["cache_dir"]
                / ("models--" + settings[f"{prefix}_id"].replace("/", "--"))
                / "snapshots"
                / settings[f"{prefix}_revision"]
            )
            if not snap.is_dir() or not any(snap.glob("*.safetensors")):
                raise SystemExit(f"Thiếu snapshot {prefix}: {snap}")
            print(f"OK ({prefix} cached): {snap}")
        else:
            path = snapshot_download(
                settings[f"{prefix}_id"],
                revision=settings[f"{prefix}_revision"],
                cache_dir=root / settings["cache_dir"],
                token=False,
                allow_patterns=[
                    "*.json",
                    "*.safetensors",
                    "*.jinja",
                    "*.txt",
                    "tokenizer.model",
                    "sentencepiece.bpe.model",
                ],
            )
            print(path)

    if not args.skip_adapter:
        prepare_adapter(
            root,
            settings,
            archive_url=args.adapter_url,
            local_archive=args.adapter_archive,
            check_only=args.check_only,
        )


if __name__ == "__main__":
    main()
