"""Unit tests for embedding cache management and atomic persistence."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from experiments.speaker_identification.cache import EmbeddingCacheManager
from experiments.speaker_identification.encoders.mfcc import MFCCEncoder


def test_embedding_cache_put_and_get(tmp_path: Path) -> None:
    cache = EmbeddingCacheManager(cache_root=tmp_path)
    encoder = MFCCEncoder()

    waveform = np.ones(16000, dtype=np.float32) * 0.1

    # Before caching
    assert cache.get(encoder, waveform) is None

    # Compute and put
    emb1 = cache.get_or_compute(encoder, waveform)
    assert isinstance(emb1, np.ndarray)
    assert emb1.size == 120

    # Retrieve from cache
    emb2 = cache.get(encoder, waveform)
    assert emb2 is not None
    assert np.allclose(emb1, emb2)

    # Different waveform
    diff_waveform = np.ones(16000, dtype=np.float32) * 0.5
    assert cache.get(encoder, diff_waveform) is None
