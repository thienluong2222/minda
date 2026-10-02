"""Deterministic episode generation and manifest serialization."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from experiments.speaker_identification.contracts import (
    EpisodeManifestRecord,
    UtteranceSample,
)


def generate_vivos_episodes(
    speakers: dict[str, list[UtteranceSample]],
    dataset_name: str,
    split_name: str,
    seed: int = 20260924,
    few_shot_k_list: tuple[int, ...] = (1, 3, 5),
    num_episodes: int = 30,
    known_count: int = 5,
    unknown_count: int = 5,
    queries_per_known: int = 5,
    queries_per_unknown: int = 5,
) -> list[EpisodeManifestRecord]:
    """Generate deterministic episodes for VIVOS train or test."""
    all_spk_ids = sorted(speakers.keys())
    total_needed = known_count + unknown_count
    if len(all_spk_ids) < total_needed:
        raise ValueError(
            f"Not enough speakers in {dataset_name}-{split_name}: "
            f"{len(all_spk_ids)} < {total_needed}"
        )

    rng = np.random.RandomState(seed)
    records: list[EpisodeManifestRecord] = []

    for k in few_shot_k_list:
        for ep_id in range(num_episodes):
            # Select known and unknown speakers
            permuted = rng.permutation(all_spk_ids).tolist()
            known_spks = sorted(permuted[:known_count])
            unknown_spks = sorted(permuted[known_count:total_needed])

            # Ensure completely disjoint
            assert not (set(known_spks) & set(unknown_spks))

            # Select support and queries for known speakers
            supp_dict: dict[str, list[dict[str, Any]]] = {}
            known_queries: list[dict[str, Any]] = []

            for spk in known_spks:
                spk_utts = sorted(speakers[spk], key=lambda u: u.utterance_id)
                needed = k + queries_per_known
                if len(spk_utts) < needed:
                    raise ValueError(
                        f"Speaker {spk} has only {len(spk_utts)} utterances, needed {needed}"
                    )

                indices = rng.permutation(len(spk_utts)).tolist()
                supp_indices = sorted(indices[:k])
                query_indices = sorted(indices[k:needed])

                # Disjoint check
                assert not (set(supp_indices) & set(query_indices))

                supp_dict[spk] = [spk_utts[i].to_dict() for i in supp_indices]
                for i in query_indices:
                    q_sample = spk_utts[i].to_dict()
                    q_sample["is_known"] = True
                    q_sample["true_speaker_id"] = spk
                    known_queries.append(q_sample)

            # Select queries for unknown speakers
            unknown_queries: list[dict[str, Any]] = []
            for spk in unknown_spks:
                spk_utts = sorted(speakers[spk], key=lambda u: u.utterance_id)
                if len(spk_utts) < queries_per_unknown:
                    raise ValueError(
                        f"Speaker {spk} has only {len(spk_utts)} utterances, "
                        f"needed {queries_per_unknown}"
                    )

                indices = rng.permutation(len(spk_utts)).tolist()
                u_query_indices = sorted(indices[:queries_per_unknown])

                for i in u_query_indices:
                    q_sample = spk_utts[i].to_dict()
                    q_sample["is_known"] = False
                    q_sample["true_speaker_id"] = spk  # evaluation label is unknown
                    unknown_queries.append(q_sample)

            # Closed-set record
            records.append(
                EpisodeManifestRecord(
                    dataset=dataset_name,
                    split=split_name,
                    episode_id=ep_id,
                    seed=seed,
                    few_shot_k=k,
                    protocol="closed_set",
                    known_speakers=known_spks,
                    unknown_speakers=[],
                    support_utterances=supp_dict,
                    query_utterances=known_queries,
                )
            )

            # Open-set record
            records.append(
                EpisodeManifestRecord(
                    dataset=dataset_name,
                    split=split_name,
                    episode_id=ep_id,
                    seed=seed,
                    few_shot_k=k,
                    protocol="open_set",
                    known_speakers=known_spks,
                    unknown_speakers=unknown_spks,
                    support_utterances=supp_dict,
                    query_utterances=known_queries + unknown_queries,
                )
            )

    return records


def generate_voxvietnam_episodes(
    support_pools: dict[str, list[UtteranceSample]],
    query_pools: dict[str, list[UtteranceSample]],
    dataset_name: str = "voxvietnam",
    split_name: str = "public_test",
    seed: int = 20260924,
    few_shot_k_list: tuple[int, ...] = (1, 3, 5),
    num_episodes: int = 30,
    known_count: int = 5,
    unknown_count: int = 5,
) -> list[EpisodeManifestRecord]:
    """Generate deterministic episodes for VoxVietnam using fixed support/query pools."""
    all_spk_ids = sorted(support_pools.keys())
    total_needed = known_count + unknown_count
    if len(all_spk_ids) < total_needed:
        raise ValueError(f"Not enough speakers in VoxVietnam: {len(all_spk_ids)} < {total_needed}")

    rng = np.random.RandomState(seed)
    records: list[EpisodeManifestRecord] = []

    for k in few_shot_k_list:
        for ep_id in range(num_episodes):
            permuted = rng.permutation(all_spk_ids).tolist()
            known_spks = sorted(permuted[:known_count])
            unknown_spks = sorted(permuted[known_count:total_needed])

            supp_dict: dict[str, list[dict[str, Any]]] = {}
            known_queries: list[dict[str, Any]] = []

            for spk in known_spks:
                spk_supp_pool = support_pools[spk]
                spk_query_pool = query_pools[spk]

                # Select k support from support pool
                supp_indices = sorted(rng.permutation(len(spk_supp_pool))[:k].tolist())
                supp_dict[spk] = [spk_supp_pool[i].to_dict() for i in supp_indices]

                # Take all 5 queries from query pool
                for q in spk_query_pool:
                    q_dict = q.to_dict()
                    q_dict["is_known"] = True
                    q_dict["true_speaker_id"] = spk
                    known_queries.append(q_dict)

            unknown_queries: list[dict[str, Any]] = []
            for spk in unknown_spks:
                spk_query_pool = query_pools[spk]
                for q in spk_query_pool:
                    q_dict = q.to_dict()
                    q_dict["is_known"] = False
                    q_dict["true_speaker_id"] = spk
                    unknown_queries.append(q_dict)

            # Closed-set
            records.append(
                EpisodeManifestRecord(
                    dataset=dataset_name,
                    split=split_name,
                    episode_id=ep_id,
                    seed=seed,
                    few_shot_k=k,
                    protocol="closed_set",
                    known_speakers=known_spks,
                    unknown_speakers=[],
                    support_utterances=supp_dict,
                    query_utterances=known_queries,
                )
            )

            # Open-set
            records.append(
                EpisodeManifestRecord(
                    dataset=dataset_name,
                    split=split_name,
                    episode_id=ep_id,
                    seed=seed,
                    few_shot_k=k,
                    protocol="open_set",
                    known_speakers=known_spks,
                    unknown_speakers=unknown_spks,
                    support_utterances=supp_dict,
                    query_utterances=known_queries + unknown_queries,
                )
            )

    return records


def save_manifest(records: list[EpisodeManifestRecord], output_path: Path | str) -> str:
    """Save records to a formatted JSON manifest and return its SHA-256 hash."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    data = [r.to_dict() for r in records]
    json_str = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    output_path.write_text(json_str, encoding="utf-8")

    return hashlib.sha256(json_str.encode("utf-8")).hexdigest()


def load_manifest(manifest_path: Path | str) -> list[EpisodeManifestRecord]:
    """Load episode manifest from JSON file."""
    path = Path(manifest_path)
    if not path.is_file():
        raise FileNotFoundError(f"Manifest not found: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    return [EpisodeManifestRecord.from_dict(item) for item in data]
