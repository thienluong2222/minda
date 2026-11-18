"""Offline MLX ASR subprocess, isolated from the Torch worker's dependencies."""

from __future__ import annotations

import hashlib
import json
import os
import select
import subprocess
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]


class MlxWhisperPipeline:
    device = "mlx"

    def __init__(self, config, cache_dir):
        self.config = config
        model = (
            Path(config.mlx_model_dir)
            if config.mlx_model_dir
            else Path(cache_dir)
            / "asr_mlx"
            / config.model_id.replace("/", "--")
            / config.model_revision
        )
        manifest = json.loads((model / "conversion.json").read_text())
        if (manifest.get("model_id"), manifest.get("revision")) != (
            config.model_id,
            config.model_revision,
        ):
            raise ValueError("MLX checkpoint không khớp model/revision đã ghim.")
        with (model / "weights.safetensors").open("rb") as weights:
            if hashlib.file_digest(weights, "sha256").hexdigest() != manifest["weights_sha256"]:
                raise ValueError("MLX checkpoint checksum mismatch.")
        python = ROOT / config.mlx_runtime_python
        if not python.is_file():
            python = ROOT.parent / config.mlx_runtime_python
        self.directory = tempfile.TemporaryDirectory(prefix="meeting-asr-mlx-")
        self.log = (Path(self.directory.name) / "runtime.log").open("w")
        self.process = subprocess.Popen(
            [str(python), str(ROOT / "scripts/asr_mlx_worker.py"), "--model", str(model.resolve())],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.log,
            text=True,
            env=dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1"),
        )

    def __call__(self, samples, *, generate_kwargs):
        path = Path(self.directory.name) / "clip.npy"
        np.save(path, samples, allow_pickle=False)
        request = {
            "audio": str(path),
            "language": self.config.language,
            "temperature": generate_kwargs.get("temperature", 0),
            "max_tokens": generate_kwargs["max_new_tokens"],
        }
        self.process.stdin.write(json.dumps(request) + "\n")
        self.process.stdin.flush()
        ready, _, _ = select.select([self.process.stdout], [], [], 240)
        if not ready:
            self.close()
            raise TimeoutError("MLX ASR vượt thời gian xử lý một đoạn.")
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError("MLX ASR đã dừng.")
        result = json.loads(line)
        if "error" in result:
            raise RuntimeError(result["error"])
        return result

    def close(self):
        process = getattr(self, "process", None)
        if process:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            for pipe in [process.stdin, process.stdout]:
                if pipe:
                    pipe.close()
            self.process = None
        if getattr(self, "log", None):
            self.log.close()
        if getattr(self, "directory", None):
            self.directory.cleanup()

    def __del__(self):
        self.close()
