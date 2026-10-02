"""Dataset loaders for VIVOS and VoxVietnam with strict split validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq

from experiments.speaker_identification.audio import load_audio_mono_16k, normalize_waveform
from experiments.speaker_identification.contracts import UtteranceSample

# Global cache for parquet tables to avoid repeated disk reads
_PARQUET_TABLE_CACHE: dict[str, Any] = {}


def clear_parquet_cache() -> None:
    """Clear memory cached parquet tables."""
    _PARQUET_TABLE_CACHE.clear()


def load_vivos_dataset(waves_dir: Path | str) -> dict[str, list[UtteranceSample]]:
    """Load VIVOS dataset split from its waves directory."""
    waves_path = Path(waves_dir)
    if not waves_path.is_dir():
        raise FileNotFoundError(f"VIVOS waves directory not found: {waves_path}")

    speakers: dict[str, list[UtteranceSample]] = {}
    speaker_dirs = sorted([p for p in waves_path.iterdir() if p.is_dir()])

    for spk_dir in speaker_dirs:
        spk_id = spk_dir.name
        wav_files = sorted(spk_dir.glob("*.wav"))
        if not wav_files:
            continue

        samples: list[UtteranceSample] = []
        for wav in wav_files:
            samples.append(
                UtteranceSample(
                    utterance_id=wav.stem,
                    speaker_id=spk_id,
                    audio_path=str(wav),
                )
            )
        speakers[spk_id] = samples

    return speakers


def load_voxvietnam_dataset(
    index_path: Path | str,
    base_dir: Path | str | None = None,
) -> tuple[dict[str, list[UtteranceSample]], dict[str, list[UtteranceSample]]]:
    """Load VoxVietnam public test subset index.

    Returns:
        (support_pool_by_speaker, query_pool_by_speaker)
        Each speaker has 5 support pool utterances and 5 query pool utterances.
    """
    idx_path = Path(index_path)
    if not idx_path.is_file():
        raise FileNotFoundError(f"VoxVietnam subset index not found: {idx_path}")

    data = json.loads(idx_path.read_text(encoding="utf-8"))

    support_pools: dict[str, list[UtteranceSample]] = {}
    query_pools: dict[str, list[UtteranceSample]] = {}

    speakers = data.get("speakers", {})
    for spk_id, spk_data in sorted(speakers.items(), key=lambda item: item[0]):
        # Support pool
        supp_samples: list[UtteranceSample] = []
        for idx, item in enumerate(spk_data.get("support_pool", [])):
            shard = str(item["shard"])
            row_idx = int(item["row_index"])
            supp_samples.append(
                UtteranceSample(
                    utterance_id=f"{spk_id}_supp_{idx}_{shard}_{row_idx}",
                    speaker_id=spk_id,
                    shard=shard,
                    row_index=row_idx,
                )
            )

        # Query pool
        query_samples: list[UtteranceSample] = []
        for idx, item in enumerate(spk_data.get("query_pool", [])):
            shard = str(item["shard"])
            row_idx = int(item["row_index"])
            query_samples.append(
                UtteranceSample(
                    utterance_id=f"{spk_id}_query_{idx}_{shard}_{row_idx}",
                    speaker_id=spk_id,
                    shard=shard,
                    row_index=row_idx,
                )
            )

        # Validate non-empty and non-overlapping
        if len(supp_samples) != 5:
            raise ValueError(
                f"Speaker {spk_id} has {len(supp_samples)} support samples, expected 5"
            )
        if len(query_samples) != 5:
            raise ValueError(f"Speaker {spk_id} has {len(query_samples)} query samples, expected 5")

        supp_keys = {(s.shard, s.row_index) for s in supp_samples}
        query_keys = {(s.shard, s.row_index) for s in query_samples}
        overlap = supp_keys & query_keys
        if overlap:
            raise ValueError(f"Data leakage detected for speaker {spk_id}: {overlap}")

        support_pools[spk_id] = supp_samples
        query_pools[spk_id] = query_samples

    return support_pools, query_pools


def load_sample_audio(
    sample: UtteranceSample,
    voxvietnam_dir: Path | str | None = None,
    target_sr: int = 16000,
) -> np.ndarray:
    """Load audio waveform corresponding to an UtteranceSample."""
    if sample.audio_path:
        return load_audio_mono_16k(sample.audio_path, target_sr=target_sr)

    if sample.shard is not None and sample.row_index is not None:
        if voxvietnam_dir is None:
            raise ValueError("voxvietnam_dir must be provided to load parquet samples")
        shard_path = Path(voxvietnam_dir) / sample.shard
        shard_str = str(shard_path)
        if shard_str not in _PARQUET_TABLE_CACHE:
            if not shard_path.is_file():
                raise FileNotFoundError(f"Parquet shard not found: {shard_path}")
            _PARQUET_TABLE_CACHE[shard_str] = pq.read_table(shard_str)

        table = _PARQUET_TABLE_CACHE[shard_str]
        row_idx = sample.row_index
        audio_data = table["audio"][row_idx].as_py()
        arr = np.asarray(audio_data["array"], dtype=np.float32)
        sr = int(audio_data.get("sampling_rate", 16000))
        return normalize_waveform(arr, target_sr=target_sr, source_sr=sr)

    raise ValueError(f"Cannot load audio for sample without audio_path or shard: {sample}")
