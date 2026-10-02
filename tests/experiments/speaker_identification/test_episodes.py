"""Unit tests for deterministic episode generation and manifest validation."""

from __future__ import annotations

import json
from pathlib import Path

from experiments.speaker_identification.contracts import UtteranceSample
from experiments.speaker_identification.episodes import (
    generate_vivos_episodes,
    generate_voxvietnam_episodes,
    load_manifest,
    save_manifest,
)


def _make_mock_speakers(
    num_speakers: int = 12, utts_per_spk: int = 25
) -> dict[str, list[UtteranceSample]]:
    speakers: dict[str, list[UtteranceSample]] = {}
    for i in range(num_speakers):
        spk_id = f"spk_{i:02d}"
        speakers[spk_id] = [
            UtteranceSample(
                utterance_id=f"{spk_id}_u{j:02d}",
                speaker_id=spk_id,
                audio_path=f"/fake/{spk_id}/u{j:02d}.wav",
            )
            for j in range(utts_per_spk)
        ]
    return speakers


def test_vivos_episodes_determinism_and_disjointness() -> None:
    speakers = _make_mock_speakers(12, 30)
    seed = 20260924

    episodes1 = generate_vivos_episodes(
        speakers,
        dataset_name="vivos",
        split_name="dev",
        seed=seed,
        few_shot_k_list=(1, 3, 5),
        num_episodes=5,
    )
    episodes2 = generate_vivos_episodes(
        speakers,
        dataset_name="vivos",
        split_name="dev",
        seed=seed,
        few_shot_k_list=(1, 3, 5),
        num_episodes=5,
    )

    # Byte-for-byte semantic equality
    assert json.dumps([e.to_dict() for e in episodes1]) == json.dumps(
        [e.to_dict() for e in episodes2]
    )

    # Check properties of each episode
    for ep in episodes1:
        assert len(ep.known_speakers) == 5
        if ep.protocol == "closed_set":
            assert len(ep.unknown_speakers) == 0
            assert len(ep.query_utterances) == 25
        else:
            assert len(ep.unknown_speakers) == 5
            assert len(ep.query_utterances) == 50
            # Known and unknown speakers are disjoint
            assert not (set(ep.known_speakers) & set(ep.unknown_speakers))

        # Check support count per speaker
        for spk, supp_list in ep.support_utterances.items():
            assert len(supp_list) == ep.few_shot_k
            # Support and query utterances for this speaker are disjoint
            supp_ids = {s["utterance_id"] for s in supp_list}
            query_ids = {
                q["utterance_id"] for q in ep.query_utterances if q["true_speaker_id"] == spk
            }
            assert not (supp_ids & query_ids)


def test_different_seeds_produce_different_episodes() -> None:
    speakers = _make_mock_speakers(12, 30)
    ep1 = generate_vivos_episodes(
        speakers, "vivos", "dev", seed=100, few_shot_k_list=(3,), num_episodes=2
    )
    ep2 = generate_vivos_episodes(
        speakers, "vivos", "dev", seed=200, few_shot_k_list=(3,), num_episodes=2
    )

    assert json.dumps([e.to_dict() for e in ep1]) != json.dumps([e.to_dict() for e in ep2])


def test_voxvietnam_episodes_determinism(tmp_path: Path) -> None:
    # 12 speakers, each 5 supp and 5 query
    supp_pools: dict[str, list[UtteranceSample]] = {}
    query_pools: dict[str, list[UtteranceSample]] = {}
    for i in range(12):
        spk = f"id_{i:02d}"
        supp_pools[spk] = [
            UtteranceSample(utterance_id=f"{spk}_s{j}", speaker_id=spk, shard="s.pq", row_index=j)
            for j in range(5)
        ]
        query_pools[spk] = [
            UtteranceSample(utterance_id=f"{spk}_q{j}", speaker_id=spk, shard="q.pq", row_index=j)
            for j in range(5)
        ]

    episodes = generate_voxvietnam_episodes(
        supp_pools,
        query_pools,
        seed=20260924,
        few_shot_k_list=(1, 3, 5),
        num_episodes=3,
    )
    assert len(episodes) == 3 * 3 * 2  # 3 K * 3 episodes * 2 protocols (closed, open) = 18

    # Test save and load round-trip
    manifest_file = tmp_path / "voxvietnam-test.json"
    sha = save_manifest(episodes, manifest_file)
    assert len(sha) == 64

    loaded = load_manifest(manifest_file)
    assert len(loaded) == len(episodes)
    assert loaded[0].episode_id == episodes[0].episode_id
