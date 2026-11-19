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
from pathlib import Path

import yaml
from huggingface_hub import snapshot_download

DEFAULT_ADAPTER_RELEASE_TAG = "lora-b-v21-ckpt132"
DEFAULT_ADAPTER_BASE_URL = (
    f"https://github.com/thienluong2222/minda/releases/download/{DEFAULT_ADAPTER_RELEASE_TAG}"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_verified(url: str, destination: Path, expected_sha256: str | None) -> None:
    if destination.is_file():
        actual = _sha256(destination)
        if not expected_sha256 or actual == expected_sha256:
            print(f"OK (cached & verified): {destination}")
            return
        print(f"Checksum mismatch on existing {destination}; re-downloading ...")

    destination.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {url} -> {destination}")
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        headers = {"User-Agent": "minda-prepare-minutes-models/1.0"}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=300) as response, tmp_path.open("wb") as out:
            shutil.copyfileobj(response, out, length=1 << 20)
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
    base_url: str,
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

    all_verified = True
    for filename, expected_sha in expected_files:
        target = adapter_dir / filename
        if not target.is_file() or (expected_sha and _sha256(target) != expected_sha):
            all_verified = False
            break
    if all_verified:
        print(f"LoRA B adapter ready & verified: {adapter_dir}")
        return

    if check_only:
        raise SystemExit(
            f"Thiếu hoặc sai checksum LoRA B adapter tại {adapter_dir}. "
            f"Chạy lại không có --check-only để tải từ {base_url}."
        )

    for filename, expected_sha in expected_files:
        url = f"{base_url.rstrip('/')}/{filename}"
        try:
            _download_verified(url, adapter_dir / filename, expected_sha)
        except urllib.error.HTTPError as exc:
            raise SystemExit(
                f"Không tải được {filename} từ {url} (HTTP {exc.code}).\n"
                f"Hãy đảm bảo GitHub Release tag '{DEFAULT_ADAPTER_RELEASE_TAG}' đã upload 2 file "
                "(adapter_config.json, adapter_model.safetensors), truyền "
                "--adapter-base-url <URL>, hoặc chạy demo bằng mô hình nền với --skip-adapter "
                "và đặt adapter_path: null trong configs/minutes.yaml."
            ) from exc


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download pinned Qwen3-4B, E5-small, and LoRA B inference weights."
    )
    parser.add_argument(
        "--adapter-base-url",
        default=os.getenv("MINDA_ADAPTER_BASE_URL", DEFAULT_ADAPTER_BASE_URL),
        help="Base URL hosting adapter_config.json and adapter_model.safetensors.",
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
        prepare_adapter(root, settings, base_url=args.adapter_base_url, check_only=args.check_only)


if __name__ == "__main__":
    main()
