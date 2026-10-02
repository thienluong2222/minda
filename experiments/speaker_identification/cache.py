"""Embedding cache manager with atomic writes and validation."""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import numpy as np

from experiments.speaker_identification.audio import compute_audio_sha256, validate_waveform
from experiments.speaker_identification.contracts import SpeakerEncoder


class EmbeddingCacheManager:
    """Manages disk-cached speaker embeddings with atomic writes and metadata."""

    def __init__(
        self,
        cache_root: Path | str = "data/evaluation_cache/speaker_embeddings",
    ) -> None:
        self.cache_root = Path(cache_root)

    def get_cache_paths(self, encoder: SpeakerEncoder, audio_sha256: str) -> tuple[Path, Path]:
        encoder_dir = self.cache_root / encoder.encoder_id / encoder.model_revision
        npy_path = encoder_dir / f"{audio_sha256}.npy"
        meta_path = encoder_dir / f"{audio_sha256}.json"
        return npy_path, meta_path

    def get(self, encoder: SpeakerEncoder, waveform: np.ndarray) -> np.ndarray | None:
        audio_sha256 = compute_audio_sha256(waveform)
        npy_path, meta_path = self.get_cache_paths(encoder, audio_sha256)

        if npy_path.is_file() and meta_path.is_file():
            try:
                emb = np.load(npy_path)
                if (
                    emb.ndim == 1
                    and emb.size == encoder.embedding_dimension
                    and np.all(np.isfinite(emb))
                ):
                    return np.asarray(emb, dtype=np.float32)
            except Exception:
                return None
        return None

    def put(
        self,
        encoder: SpeakerEncoder,
        waveform: np.ndarray,
        embedding: np.ndarray,
    ) -> None:
        validate_waveform(waveform)
        if (
            embedding.ndim != 1
            or embedding.size != encoder.embedding_dimension
            or not np.all(np.isfinite(embedding))
        ):
            raise ValueError(f"Invalid embedding to cache: shape {embedding.shape}")

        audio_sha256 = compute_audio_sha256(waveform)
        npy_path, meta_path = self.get_cache_paths(encoder, audio_sha256)
        npy_path.parent.mkdir(parents=True, exist_ok=True)

        meta = {
            "audio_sha256": audio_sha256,
            "encoder_id": encoder.encoder_id,
            "model_id": encoder.model_id,
            "model_revision": encoder.model_revision,
            "sample_rate": encoder.sample_rate,
            "embedding_dimension": encoder.embedding_dimension,
            "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
            "norm": float(np.linalg.norm(embedding)),
        }

        # Atomic write via temporary files
        tmp_npy = npy_path.with_name(f"{npy_path.stem}.tmp.npy")
        tmp_meta = meta_path.with_name(f"{meta_path.stem}.tmp.json")

        with open(tmp_npy, "wb") as f:
            np.save(f, embedding.astype(np.float32))
        tmp_meta.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

        tmp_npy.replace(npy_path)
        tmp_meta.replace(meta_path)

    def get_or_compute(self, encoder: SpeakerEncoder, waveform: np.ndarray) -> np.ndarray:
        cached = self.get(encoder, waveform)
        if cached is not None:
            return cached

        emb = encoder.encode(waveform)
        self.put(encoder, waveform, emb)
        return emb
