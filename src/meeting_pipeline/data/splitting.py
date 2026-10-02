"""Speaker-disjoint splitting and enrollment partitioning for VIVOS.

Specification: Section 6 of docs/PLAN_VIVOS_SYNTHETIC_PIPELINE.md.
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Any

from meeting_pipeline.data.manifest import save_manifest_jsonl, scan_vivos_split
from meeting_pipeline.domain.contracts import UtteranceRecord, VivosDataConfig

logger = logging.getLogger(__name__)


def partition_vivos_splits(
    config: VivosDataConfig,
) -> tuple[list[UtteranceRecord], dict[str, Any], dict[str, list[str]]]:
    """Scan VIVOS, partition speakers into dev/val/test, and separate enrollment audio.

    Rules:
    1. Speaker-disjoint: Dev, Val, Test have 0 overlapping speakers.
    2. Utterance-disjoint: Enrollment audio is strictly excluded from meeting synthesis.
    3. Reproducible: Deterministic seeding.
    """
    vivos_root = Path(config.vivos_root)
    train_dir = vivos_root / "train"
    test_dir = vivos_root / "test"

    if not train_dir.exists() or not test_dir.exists():
        raise FileNotFoundError(f"VIVOS train/test directories not found in {vivos_root}")

    # Scan raw files without split assignment first
    raw_train_records = scan_vivos_split(train_dir, assigned_split="development")
    raw_test_records = scan_vivos_split(test_dir, assigned_split="test")

    # Group train records by speaker
    train_speakers = sorted(list({r.speaker_id for r in raw_train_records}))
    test_speakers = sorted(list({r.speaker_id for r in raw_test_records}))

    # Shuffle train speakers deterministically
    rng = random.Random(config.seed)
    shuffled_train_speakers = list(train_speakers)
    rng.shuffle(shuffled_train_speakers)

    dev_spk_count = config.development_speaker_count
    dev_speakers = sorted(shuffled_train_speakers[:dev_spk_count])
    val_speakers = sorted(shuffled_train_speakers[dev_spk_count:])

    dev_speaker_set = set(dev_speakers)
    val_speaker_set = set(val_speakers)
    test_speaker_set = set(test_speakers)

    # Re-assign split based on speaker partition
    all_raw_records = raw_train_records + raw_test_records
    speaker_to_records: dict[str, list[UtteranceRecord]] = {}

    for r in all_raw_records:
        if r.speaker_id in dev_speaker_set:
            assigned = "development"
        elif r.speaker_id in val_speaker_set:
            assigned = "validation"
        elif r.speaker_id in test_speaker_set:
            assigned = "test"
        else:
            raise ValueError(f"Unmapped speaker {r.speaker_id}")

        r.split = assigned  # type: ignore[assignment]
        speaker_to_records.setdefault(r.speaker_id, []).append(r)

    # For each speaker, partition enrollment utterances
    enrollment_catalog: dict[str, list[str]] = {}
    final_records: list[UtteranceRecord] = []

    for spk_id, spk_records in sorted(speaker_to_records.items()):
        # Sort utterances deterministically
        spk_records = sorted(spk_records, key=lambda x: x.utterance_id)

        accumulated_dur = 0.0
        accumulated_count = 0
        spk_enrollment_ids: list[str] = []

        for r in spk_records:
            if (
                accumulated_dur < config.min_enrollment_duration_sec
                or accumulated_count < config.min_enrollment_utterances
            ):
                r.is_enrollment = True
                accumulated_dur += r.duration_sec
                accumulated_count += 1
                spk_enrollment_ids.append(r.utterance_id)
            else:
                r.is_enrollment = False

            final_records.append(r)

        enrollment_catalog[spk_id] = spk_enrollment_ids

        logger.info(
            "Speaker %s: %d enrollment utts (%.1fs), %d meeting utts",
            spk_id,
            len(spk_enrollment_ids),
            accumulated_dur,
            len(spk_records) - len(spk_enrollment_ids),
        )

    splits_manifest = {
        "seed": config.seed,
        "development_speakers": dev_speakers,
        "validation_speakers": val_speakers,
        "test_speakers": test_speakers,
        "speaker_counts": {
            "development": len(dev_speakers),
            "validation": len(val_speakers),
            "test": len(test_speakers),
            "total": len(dev_speakers) + len(val_speakers) + len(test_speakers),
        },
        "utterance_counts": {
            "development": sum(1 for r in final_records if r.split == "development"),
            "validation": sum(1 for r in final_records if r.split == "validation"),
            "test": sum(1 for r in final_records if r.split == "test"),
            "total": len(final_records),
        },
    }

    return final_records, splits_manifest, enrollment_catalog


def build_and_save_vivos_data(config: VivosDataConfig) -> None:
    """Build manifest, splits, and enrollment catalog, then write to disk."""
    records, splits, catalog = partition_vivos_splits(config)

    save_manifest_jsonl(records, config.manifest_output_path)

    splits_path = Path(config.splits_output_path)
    splits_path.parent.mkdir(parents=True, exist_ok=True)
    with open(splits_path, "w", encoding="utf-8") as f:
        json.dump(splits, f, ensure_ascii=False, indent=2)

    catalog_path = Path(config.catalog_output_path)
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    with open(catalog_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)

    logger.info(
        "Successfully saved %d records to %s, splits to %s, catalog to %s",
        len(records),
        config.manifest_output_path,
        config.splits_output_path,
        config.catalog_output_path,
    )
