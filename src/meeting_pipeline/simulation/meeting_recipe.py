"""Meeting recipe generator for canonical multi-device simulations.

Specification: Section 5.2 & 7 of docs/PLAN_VIVOS_SYNTHETIC_PIPELINE.md.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import random
from pathlib import Path

from meeting_pipeline.domain.contracts import (
    DeviceConfig,
    MeetingRecipe,
    RoomConfig,
    SimulationProfileConfig,
    TurnRecord,
    UtteranceRecord,
)

logger = logging.getLogger(__name__)


def generate_meeting_recipe(
    meeting_id: str,
    split: str,
    seed: int,
    profile: SimulationProfileConfig,
    manifest_records: list[UtteranceRecord],
    enrollment_catalog: dict[str, list[str]],
    manifest_path: str = "data/manifests/vivos.jsonl",
    config_path: str = "",
) -> MeetingRecipe:
    """Generate a canonical meeting recipe.

    Guarantees:
    - All speakers are drawn strictly from the specified split.
    - Enrollment utterances are excluded from turns.
    - No overlapping turns (`overlap=false`).
    - Turn pauses within configured range (0.6 - 1.2s).
    - At least two speakers have different nearest devices.
    """
    rng = random.Random(seed)

    # 1. Filter eligible speakers and meeting utterances in split
    split_records = [r for r in manifest_records if r.split == split]
    speaker_meeting_utts: dict[str, list[UtteranceRecord]] = {}

    for r in split_records:
        if not r.is_enrollment:
            speaker_meeting_utts.setdefault(r.speaker_id, []).append(r)

    eligible_speakers = sorted(
        [spk for spk, utts in speaker_meeting_utts.items() if len(utts) >= 10]
    )

    if len(eligible_speakers) < profile.num_speakers:
        raise ValueError(
            f"Not enough eligible speakers in split '{split}' "
            f"(found {len(eligible_speakers)}, needed {profile.num_speakers})"
        )

    # Select speakers for this meeting
    selected_speakers = sorted(rng.sample(eligible_speakers, profile.num_speakers))

    # 2. Build turns sequence until target duration is reached
    target_duration = rng.uniform(
        profile.min_meeting_duration_sec,
        profile.max_meeting_duration_sec,
    )

    turns: list[TurnRecord] = []
    current_time = rng.uniform(0.5, 1.5)  # initial leading pause
    turn_idx = 0

    speaker_utt_pools = {spk: list(speaker_meeting_utts[spk]) for spk in selected_speakers}
    for pool in speaker_utt_pools.values():
        rng.shuffle(pool)

    speaker_pool_pointers = {spk: 0 for spk in selected_speakers}
    last_speaker: str | None = None

    while current_time < target_duration:
        # Choose next speaker different from last_speaker
        candidate_speakers = [s for s in selected_speakers if s != last_speaker]
        spk = rng.choice(candidate_speakers)
        last_speaker = spk

        ptr = speaker_pool_pointers[spk]
        pool = speaker_utt_pools[spk]
        utt = pool[ptr % len(pool)]
        speaker_pool_pointers[spk] += 1

        start_sec = current_time
        end_sec = start_sec + utt.duration_sec

        turn = TurnRecord(
            turn_id=f"turn_{turn_idx:04d}",
            speaker_id=spk,
            utterance_id=utt.utterance_id,
            start_sec=round(start_sec, 3),
            end_sec=round(end_sec, 3),
            text_raw=utt.text_raw,
            text_normalized=utt.text_normalized,
        )
        turns.append(turn)
        turn_idx += 1

        # Insert pause between turns (e.g. 0.6 to 1.2s)
        pause = rng.uniform(profile.turn_pause_range[0], profile.turn_pause_range[1])
        current_time = end_sec + pause

    canonical_duration = round(current_time + 1.0, 3)

    # 3. Spatial geometry: 3D room, speakers, and devices
    dims = profile.room_dimensions
    cx, cy = dims[0] / 2.0, dims[1] / 2.0

    # Place speakers in an oval around the table at z = 1.2m
    speaker_positions: dict[str, list[float]] = {}
    radius_x, radius_y = min(1.5, dims[0] / 3.0), min(1.0, dims[1] / 3.0)
    for i, spk in enumerate(selected_speakers):
        angle = (2 * math.pi * i) / len(selected_speakers)
        sx = round(cx + radius_x * math.cos(angle), 3)
        sy = round(cy + radius_y * math.sin(angle), 3)
        speaker_positions[spk] = [sx, sy, 1.2]

    # Place devices on the table at z = 0.8m
    # Use smaller radius so devices are situated in front of different seats
    device_positions: dict[str, list[float]] = {}
    dev_radius_x, dev_radius_y = radius_x * 0.6, radius_y * 0.6
    device_ids = [f"device_{d:02d}" for d in range(1, profile.num_devices + 1)]

    for j, dev_id in enumerate(device_ids):
        angle = (2 * math.pi * j) / len(device_ids) + 0.2  # slight offset
        dx = round(cx + dev_radius_x * math.cos(angle), 3)
        dy = round(cy + dev_radius_y * math.sin(angle), 3)
        device_positions[dev_id] = [dx, dy, 0.8]

    # Ensure constraint: at least two speakers have different nearest devices
    nearest_devices = {}
    for spk, spk_pos in speaker_positions.items():
        best_dev = None
        min_dist = float("inf")
        for dev_id, dev_pos in device_positions.items():
            dist = math.dist(spk_pos, dev_pos)
            if dist < min_dist:
                min_dist = dist
                best_dev = dev_id
        nearest_devices[spk] = best_dev

    unique_nearest = len(set(nearest_devices.values()))
    if unique_nearest < 2 and len(selected_speakers) >= 2:
        logger.warning(
            "Geometry had < 2 distinct nearest devices (%d); adjusting placement",
            unique_nearest,
        )
        # Shift first device closer to speaker 0
        s0_pos = speaker_positions[selected_speakers[0]]
        device_positions[device_ids[0]] = [
            round((s0_pos[0] + cx) / 2, 3),
            round((s0_pos[1] + cy) / 2, 3),
            0.8,
        ]

    # 4. Device configurations
    rt60_val = rng.uniform(profile.rt60_range[0], profile.rt60_range[1])
    devices: dict[str, DeviceConfig] = {}

    for dev_id in device_ids:
        snr = rng.uniform(profile.snr_db_range[0], profile.snr_db_range[1])
        offset = rng.uniform(profile.offset_sec_range[0], profile.offset_sec_range[1])
        drift = rng.uniform(profile.drift_ppm_range[0], profile.drift_ppm_range[1])
        clip_ratio = rng.uniform(
            profile.clipping_ratio_range[0],
            profile.clipping_ratio_range[1],
        )
        dropout_cnt = rng.randint(
            profile.dropout_count_range[0],
            profile.dropout_count_range[1],
        )
        noise_t = rng.choice(profile.noise_types)

        devices[dev_id] = DeviceConfig(
            device_id=dev_id,
            position=device_positions[dev_id],
            gain_db=round(rng.uniform(-2.0, 2.0), 2),
            snr_db=round(snr, 1),
            noise_type=noise_t,
            drift_ppm=round(drift, 2),
            offset_sec=round(offset, 4),
            clipping_ratio=round(clip_ratio, 4),
            dropout_count=dropout_cnt,
        )

    # Hashes
    manifest_hash = (
        hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest()
        if Path(manifest_path).exists()
        else "unknown_manifest_hash"
    )
    config_hash = (
        hashlib.sha256(Path(config_path).read_bytes()).hexdigest()
        if config_path and Path(config_path).exists()
        else "unknown_config_hash"
    )

    enrollment_subset = {spk: enrollment_catalog.get(spk, []) for spk in selected_speakers}

    recipe = MeetingRecipe(
        schema_version="1.0",
        meeting_id=meeting_id,
        split=split,  # type: ignore[arg-type]
        seed=seed,
        profile=profile.profile_name,
        speakers=selected_speakers,
        speaker_positions=speaker_positions,
        enrollment_utterances=enrollment_subset,
        turns=turns,
        room=RoomConfig(dimensions=dims, rt60=round(rt60_val, 3)),
        devices=devices,
        canonical_duration_sec=canonical_duration,
        manifest_hash=manifest_hash,
        config_hash=config_hash,
    )

    return recipe


def save_recipe(recipe: MeetingRecipe, output_path: Path | str) -> None:
    """Save recipe to JSON file."""
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(recipe.model_dump_json(indent=2))


def load_recipe(recipe_path: Path | str) -> MeetingRecipe:
    """Load recipe from JSON file."""
    p = Path(recipe_path)
    if not p.exists():
        raise FileNotFoundError(f"Recipe file not found: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    return MeetingRecipe.model_validate(data)
