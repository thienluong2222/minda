"""Explicitly download pinned LLM and embedding weights once, and verify bundled LoRA B checksums.

Runtime inference itself always stays offline and verifies SHA-256 digests.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import yaml
from huggingface_hub import snapshot_download


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_adapter(root: Path, settings: dict) -> None:
    adapter_rel = settings.get("adapter_path")
    if not adapter_rel:
        print("adapter_path is null in configs/minutes.yaml; skipping LoRA adapter check.")
        return

    adapter_dir = (root / adapter_rel).resolve()
    checks = [
        ("adapter_config.json", settings.get("adapter_config_sha256")),
        ("adapter_model.safetensors", settings.get("adapter_sha256")),
    ]
    for filename, expected_sha in checks:
        target = adapter_dir / filename
        if not target.is_file():
            raise SystemExit(
                f"Thiếu tệp LoRA B adapter: {target}. "
                "Kiểm tra lại bản git clone đầy đủ hoặc đặt adapter_path: null trong "
                "configs/minutes.yaml để chạy mô hình nền."
            )
        if expected_sha:
            actual = _sha256(target)
            if actual != expected_sha:
                raise SystemExit(
                    f"Sai checksum SHA-256 cho {target}: expected {expected_sha}, got {actual}"
                )
    print(f"LoRA B adapter ready & verified: {adapter_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download pinned Qwen3-4B & E5-small weights and verify LoRA B checksums."
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Verify local snapshots and LoRA B checksums without downloading.",
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

    verify_adapter(root, settings)


if __name__ == "__main__":
    main()
