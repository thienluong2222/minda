"""Small official runtime/config/OCR downloads, isolated from application settings."""

from __future__ import annotations

import hashlib
import io
import runpy
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.comparative_benchmark.common import CACHE, OUT, log, read_json, sha, write_json


def main():
    import requests
    import yaml
    from huggingface_hub import hf_hub_download

    records = []
    for row in read_json(OUT / "model_inventory.json"):
        if row["model_id"].startswith("BUT-FIT/") and row["status"] == "ready":
            p = hf_hub_download(
                row["model_id"], "config.toml", revision=row["revision"], cache_dir=str(CACHE)
            )
            records.append(
                {
                    "type": "diarizen_config",
                    "model_id": row["model_id"],
                    "path": p,
                    "sha256": sha(Path(p)),
                    "revision": row["revision"],
                }
            )
    destination = OUT / "ocr/models"
    destination.mkdir(parents=True, exist_ok=True)
    easy = (
        runpy.run_path(str(OUT.parents[2] / "not_a_path"))
        if False
        else runpy.run_path(
            str(Path(sys.prefix) / "lib/python3.11/site-packages/easyocr/config.py")
        )
    )
    info = easy["recognition_models"]["gen2"]["latin_g2"]
    path = destination / info["filename"]
    if not path.exists():
        response = requests.get(info["url"], timeout=90)
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            path.write_bytes(archive.read(info["filename"]))
    assert hashlib.md5(path.read_bytes()).hexdigest() == info["md5sum"]
    records.append(
        {
            "type": "easyocr_latin_g2",
            "url": info["url"],
            "path": str(path),
            "sha256": sha(path),
            "author_md5_verified": True,
        }
    )
    log("EasyOCR Latin weights ready")
    base_url = "https://raw.githubusercontent.com/pbcquoc/vietocr/master/config/"

    def config(name):
        response = requests.get(base_url + name, timeout=30)
        response.raise_for_status()
        return yaml.safe_load(response.text)

    base = config("base.yml")
    for name, file in (
        ("vgg_transformer", "vgg-transformer.yml"),
        ("vgg_seq2seq", "vgg-seq2seq.yml"),
    ):
        cfg = {**base, **config(file)}
        path = destination / (name + ".pth")
        uri = cfg["weights"]
        if not path.exists():
            response = requests.get(uri, timeout=120)
            response.raise_for_status()
            path.write_bytes(response.content)
        cfg["weights"] = str(path)
        cfg["device"] = "cpu"
        cfg.setdefault("cnn", {})["pretrained"] = False
        write_json(destination / (name + ".json"), cfg)
        records.append(
            {
                "type": "vietocr",
                "model": name,
                "weights_url": uri,
                "path": str(path),
                "sha256": sha(path),
            }
        )
        log(name + " weights ready")
    response = requests.get(
        "https://api.github.com/repos/tesseract-ocr/tessdata_best/commits/main", timeout=30
    )
    response.raise_for_status()
    revision = response.json()["sha"]
    for language in ("vie", "eng"):
        path = destination / "tessdata_best" / (language + ".traineddata")
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/{revision}/{language}.traineddata"
        if not path.exists():
            response = requests.get(url, timeout=90)
            response.raise_for_status()
            path.write_bytes(response.content)
        records.append(
            {
                "type": "tessdata_best",
                "language": language,
                "revision": revision,
                "path": str(path),
                "sha256": sha(path),
                "url": url,
            }
        )
    write_json(OUT / "extra_model_inventory.json", records)


if __name__ == "__main__":
    main()
