"""Fetch only non-LLM inference files into the experiment/model cache."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.comparative_benchmark.common import CACHE, OUT, log, read_json, write_json

MODELS = {
    "asr": [
        "vinai/PhoWhisper-small",
        "vinai/PhoWhisper-medium",
        "openai/whisper-large-v3-turbo",
        "nguyenvulebinh/wav2vec2-base-vietnamese-250h",
        "vinai/PhoWhisper-large",
    ],
    "vad": ["speechbrain/vad-crdnn-libriparty", "funasr/fsmn-vad"],
    "segmentation": [
        "pyannote/segmentation",
        "BUT-FIT/diarizen-wavlm-base-s80-md",
        "BUT-FIT/diarizen-wavlm-large-s80-md",
        "BUT-FIT/diarizen-wavlm-large-s80-md-v2",
    ],
    "text": [
        "intfloat/multilingual-e5-small",
        "intfloat/multilingual-e5-base",
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "BAAI/bge-m3",
    ],
    "separation": [
        "speechbrain/sepformer-wham",
        "speechbrain/sepformer-libri2mix",
        "mpariente/ConvTasNet_WHAM_sepclean",
    ],
    "ocr": ["PaddlePaddle/latin_PP-OCRv5_mobile_rec"],
}


def main() -> None:
    from huggingface_hub import HfApi, snapshot_download

    parser = argparse.ArgumentParser()
    parser.add_argument("--groups", nargs="+", choices=list(MODELS), default=list(MODELS))
    parser.add_argument("--metadata-only", action="store_true")
    args = parser.parse_args()
    records = (
        read_json(OUT / "model_inventory.json") if (OUT / "model_inventory.json").exists() else []
    )
    by_id = {row["model_id"]: row for row in records}
    api = HfApi()
    for group in args.groups:
        for model_id in MODELS[group]:
            row = by_id.get(model_id, {"model_id": model_id, "group": group})
            by_id[model_id] = row
            try:
                log(f"Resolve {model_id}")
                info = api.model_info(model_id, files_metadata=True, timeout=25)
                revision = row.get("revision") or info.sha
                if revision != info.sha:
                    info = api.model_info(
                        model_id, revision=revision, files_metadata=True, timeout=25
                    )
                row.update(revision=revision, gated=bool(info.gated))
                files = [
                    f
                    for f in info.siblings
                    if not f.rfilename.endswith(
                        (
                            ".md",
                            ".png",
                            ".jpg",
                            ".wav",
                            ".flac",
                            ".onnx",
                            ".tflite",
                            ".h5",
                            ".msgpack",
                        )
                    )
                ]
                has_safe = any(
                    f.rfilename.endswith(".safetensors") and "/" not in f.rfilename for f in files
                )
                allowed = []
                for item in files:
                    name = item.rfilename
                    if name.startswith(("onnx/", "openvino/", "tf_model", "flax_model", ".")):
                        continue
                    if any(
                        s in name
                        for s in (
                            "optimizer",
                            "dataloader",
                            "lr_scheduler",
                            "counter.ckpt",
                            "brain.ckpt",
                            "example",
                            "hyperparams_train",
                        )
                    ):
                        continue
                    if has_safe and name.endswith(".bin"):
                        continue
                    if name.endswith(
                        (
                            ".json",
                            ".yaml",
                            ".yml",
                            ".txt",
                            ".safetensors",
                            ".bin",
                            ".ckpt",
                            ".pth",
                            ".pt",
                            ".model",
                            ".npz",
                            ".pkl",
                            ".py",
                            ".mvn",
                            ".pdiparams",
                            ".pdmodel",
                        )
                    ):
                        allowed.append(name)
                row["files"] = allowed
                row["estimated_bytes"] = sum(
                    int(f.size or 0) for f in files if f.rfilename in allowed
                )
                if args.metadata_only:
                    row["status"] = "resolved"
                else:
                    if shutil.disk_usage(CACHE).free < row["estimated_bytes"] + 5_000_000_000:
                        raise RuntimeError("Insufficient free disk for download plus 5GB reserve")
                    path = snapshot_download(
                        model_id,
                        revision=revision,
                        cache_dir=str(CACHE),
                        allow_patterns=allowed,
                        max_workers=2,
                    )
                    row.update(status="ready", path=path)
                    log(f"Ready {model_id}")
                row.pop("error", None)
            except Exception as exc:
                row.update(status="unavailable", error=f"{type(exc).__name__}: {str(exc)[:800]}")
                log(f"Unavailable {model_id}: {row['error'][:180]}")
            write_json(OUT / "model_inventory.json", list(by_id.values()))
    print(
        json.dumps(
            [
                {k: r.get(k) for k in ("model_id", "status", "revision", "estimated_bytes")}
                for r in by_id.values()
            ],
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
