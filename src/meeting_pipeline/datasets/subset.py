"""Leakage-resistant subset indexes; audio remains in immutable source shards."""

from __future__ import annotations

import json
import random
import tempfile
from collections import defaultdict
from pathlib import Path

import pyarrow.parquet as pq


def build_voxvietnam_subset_index(
    shard_paths: list[Path],
    output_path: Path,
    seed: int,
    utterances_per_speaker: int = 10,
    support_pool_size: int = 5,
) -> dict[str, object]:
    """Create a balanced public-test index with disjoint support/query rows.

    Only the speaker column is read. Row references preserve the source shard and
    make later audio extraction reproducible without duplicating the full corpus.
    """
    if not 0 < support_pool_size < utterances_per_speaker:
        raise ValueError("support_pool_size must leave at least one query utterance")
    rows_by_speaker: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for shard_path in sorted(shard_paths):
        table = pq.read_table(shard_path, columns=["speaker"])
        for row_index, speaker in enumerate(table.column("speaker").to_pylist()):
            rows_by_speaker[str(speaker)].append((shard_path.name, row_index))
    rng = random.Random(seed)
    speakers: dict[str, dict[str, list[dict[str, int | str]]]] = {}
    for speaker_id in sorted(rows_by_speaker):
        candidates = rows_by_speaker[speaker_id]
        if len(candidates) < utterances_per_speaker:
            continue
        selected = rng.sample(candidates, utterances_per_speaker)
        speakers[speaker_id] = {
            "support_pool": _encode_rows(selected[:support_pool_size]),
            "query_pool": _encode_rows(selected[support_pool_size:]),
        }
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "dataset_id": "voxvietnam",
        "split": "public_test",
        "seed": seed,
        "utterances_per_speaker": utterances_per_speaker,
        "support_pool_size": support_pool_size,
        "speaker_count": len(speakers),
        "speakers": speakers,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=output_path.parent, delete=False
    ) as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        temporary = Path(stream.name)
    temporary.replace(output_path)
    return payload


def _encode_rows(values: list[tuple[str, int]]) -> list[dict[str, int | str]]:
    """Serialize stable shard/row references for a subset pool."""
    return [{"shard": shard, "row_index": row_index} for shard, row_index in values]
