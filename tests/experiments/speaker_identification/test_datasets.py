"""Unit tests for dataset loading and leakage prevention."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from experiments.speaker_identification.datasets import (
    load_sample_audio,
    load_vivos_dataset,
    load_voxvietnam_dataset,
)


def test_vivos_test_dataset_structure() -> None:
    test_dir = Path("data/external/vivos/extracted/vivos/test/waves")
    if not test_dir.is_dir():
        pytest.skip("VIVOS test dataset not found")

    speakers = load_vivos_dataset(test_dir)
    assert len(speakers) == 19
    for spk_id, samples in speakers.items():
        assert len(samples) >= 20
        for sample in samples:
            assert sample.speaker_id == spk_id
            assert sample.audio_path is not None
            assert Path(sample.audio_path).is_file()


def test_vivos_train_dataset_structure() -> None:
    train_dir = Path("data/external/vivos/extracted/vivos/train/waves")
    if not train_dir.is_dir():
        pytest.skip("VIVOS train dataset not found")

    speakers = load_vivos_dataset(train_dir)
    assert len(speakers) == 46
    for spk_id, samples in speakers.items():
        assert len(samples) >= 50
        for sample in samples:
            assert sample.speaker_id == spk_id


def test_voxvietnam_subset_loading_and_leakage() -> None:
    idx_path = Path("data/external/voxvietnam/subset-index.json")
    if not idx_path.is_file():
        pytest.skip("VoxVietnam subset-index.json not found")

    support_pools, query_pools = load_voxvietnam_dataset(idx_path)
    assert len(support_pools) == 31
    assert len(query_pools) == 31
    assert set(support_pools.keys()) == set(query_pools.keys())

    for spk_id in support_pools:
        supp = support_pools[spk_id]
        query = query_pools[spk_id]
        assert len(supp) == 5
        assert len(query) == 5

        # Strict non-overlap check
        supp_locs = {(s.shard, s.row_index) for s in supp}
        query_locs = {(s.shard, s.row_index) for s in query}
        assert not (supp_locs & query_locs), f"Overlap found in {spk_id}"


def test_load_sample_audio_vivos() -> None:
    test_dir = Path("data/external/vivos/extracted/vivos/test/waves")
    if not test_dir.is_dir():
        pytest.skip("VIVOS test dataset not found")

    speakers = load_vivos_dataset(test_dir)
    first_spk = next(iter(speakers.values()))
    first_sample = first_spk[0]

    wave = load_sample_audio(first_sample)
    assert isinstance(wave, np.ndarray)
    assert wave.dtype == np.float32
    assert wave.ndim == 1
    assert len(wave) > 0
    assert np.all(np.isfinite(wave))


def test_load_sample_audio_voxvietnam() -> None:
    idx_path = Path("data/external/voxvietnam/subset-index.json")
    v_dir = Path("data/external/voxvietnam")
    if not idx_path.is_file():
        pytest.skip("VoxVietnam subset-index.json not found")

    support_pools, _ = load_voxvietnam_dataset(idx_path)
    first_spk = next(iter(support_pools.values()))
    first_sample = first_spk[0]

    wave = load_sample_audio(first_sample, voxvietnam_dir=v_dir)
    assert isinstance(wave, np.ndarray)
    assert wave.dtype == np.float32
    assert wave.ndim == 1
    assert len(wave) > 0
    assert np.all(np.isfinite(wave))
