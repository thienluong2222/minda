"""Explicitly download pinned weights once; generation itself stays offline."""

from pathlib import Path

import yaml
from huggingface_hub import snapshot_download

root = Path(__file__).resolve().parent.parent
settings = yaml.safe_load((root / "configs/minutes.yaml").read_text())
for prefix in ("model", "embedding"):
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
