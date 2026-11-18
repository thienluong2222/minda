"""Deterministic synthetic meetings from held-out, human-transcribed VIVOS audio."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.comparative_benchmark.common import (
    OUT,
    ROOT,
    SEED,
    log,
    read_json,
    setup,
    sha,
    write_json,
)

PROFILES = {
    "easy": {"rt60": 0.12, "snr": 25.0, "overlap": 0.0},
    "moderate": {"rt60": 0.3, "snr": 15.0, "overlap": 0.5},
    "stress": {"rt60": 0.55, "snr": 5.0, "overlap": 1.2},
}


def degrade(wave, condition, seed, source=0):
    import numpy as np
    from scipy.signal import fftconvolve

    rng = np.random.default_rng(seed)
    spec = PROFILES[condition]
    t = np.arange(round(spec["rt60"] * 16000)) / 16000
    rir = np.exp(-6.9078 * t / spec["rt60"]) * rng.normal(0, 0.035, len(t))
    rir[0] = 1.0
    reverberant = fftconvolve(wave, rir).astype(np.float32)[: len(wave)]
    noise = rng.normal(size=len(wave)).astype(np.float32)
    snr = spec["snr"] - 3 * source
    noise *= np.sqrt(np.mean(reverberant**2) / (10 ** (snr / 10) * np.mean(noise**2) + 1e-12))
    result = reverberant + noise
    if condition == "stress":
        limit = max(float(np.sqrt(np.mean(result**2))) * 3, 0.03)
        result = np.clip(result, -limit, limit)
    peak = np.max(np.abs(result))
    if peak > 0.98:
        result *= 0.98 / peak
    return result


def meetings():
    import numpy as np
    import soundfile as sf
    from scipy.signal import fftconvolve

    from meeting_pipeline.simulation.room import compute_room_rirs

    records = [
        json.loads(line) for line in (ROOT / "data/manifests/vivos.jsonl").read_text().splitlines()
    ]
    all_cases = []
    for split, number in (("development", 3), ("validation", 9), ("test", 30)):
        pool = [
            r
            for r in records
            if r["split"] == split and not r["is_enrollment"] and 2 <= r["duration_sec"] <= 6
        ]
        by_speaker = {
            speaker: [r for r in pool if r["speaker_id"] == speaker]
            for speaker in sorted({r["speaker_id"] for r in pool})
        }
        for index in range(number):
            condition = ("easy", "moderate", "stress")[index % 3]
            device_count = (1, 2, 4)[(index // 3) % 3]
            seed = SEED + {"development": 10000, "validation": 20000, "test": 30000}[split] + index
            rng = np.random.default_rng(seed)
            speakers = sorted(rng.choice(sorted(by_speaker), 3, replace=False).tolist())
            case_id = f"{split}_{index:03d}_{condition}_{device_count}mic"
            folder = OUT / "simulation" / case_id
            folder.mkdir(parents=True, exist_ok=True)
            if (folder / "recipe.json").exists():
                all_cases.append(read_json(folder / "recipe.json"))
                continue
            turns = []
            clock = 0.75
            used = set()
            audio = {}
            for turn_index, speaker in enumerate([*speakers, speakers[0]]):
                choices = [r for r in by_speaker[speaker] if r["utterance_id"] not in used]
                row = choices[int(rng.integers(len(choices)))]
                used.add(row["utterance_id"])
                wave, sr = sf.read(ROOT / row["audio_path"], dtype="float32")
                assert sr == 16000
                if turn_index == 2:
                    clock -= PROFILES[condition]["overlap"] + 0.35
                start = round(clock * 16000)
                end = start + len(wave)
                turns.append(
                    {
                        "speaker": speaker,
                        "origin_id": row["utterance_id"],
                        "source_sha256": row["audio_sha256"],
                        "start_sec": start / 16000,
                        "end_sec": end / 16000,
                        "reference": row["text_normalized"],
                    }
                )
                audio[turn_index] = wave
                clock = end / 16000 + 0.35
            samples = round((clock + 0.65) * 16000)
            stems = {speaker: np.zeros(samples, dtype=np.float32) for speaker in speakers}
            for i, turn in enumerate(turns):
                a = round(turn["start_sec"] * 16000)
                b = a + len(audio[i])
                stems[turn["speaker"]][a:b] += audio[i]
            positions = {
                speaker: [1.5 + i * 1.5, 1.3 + (i % 2) * 1.2, 1.2]
                for i, speaker in enumerate(speakers)
            }
            devices = {f"source-{i + 1}": [1.3 + i * 0.9, 2.2, 0.85] for i in range(device_count)}
            rirs = compute_room_rirs(
                dimensions=[6.0, 4.0, 2.8],
                rt60=PROFILES[condition]["rt60"],
                speaker_positions=positions,
                device_positions=devices,
                sample_rate=16000,
            )
            sources = []
            for source_index, source_id in enumerate(devices):
                individual = {
                    s: fftconvolve(stems[s], rirs[s][source_id]).astype(np.float32)[:samples]
                    for s in speakers
                }
                clean = sum(individual.values())
                noise = rng.normal(size=samples).astype(np.float32)
                snr = PROFILES[condition]["snr"] - 3 * source_index
                noise *= np.sqrt(np.mean(clean**2) / (10 ** (snr / 10) * np.mean(noise**2) + 1e-12))
                rendered = clean + noise
                if condition == "stress":
                    limit = max(3.5 * float(np.sqrt(np.mean(rendered**2))), 0.02)
                    rendered = np.clip(rendered, -limit, limit)
                gain = min(1.0, 0.95 / max(float(np.max(np.abs(rendered))), 1e-8))
                rendered *= gain
                # Explicit known source offsets exercise the unchanged synchronizer.
                offset_samples = source_index * 640
                rendered = np.pad(rendered, (offset_samples, 0))
                path = folder / f"{source_id}.wav"
                sf.write(path, rendered, 16000, subtype="PCM_16")
                source = {
                    "id": source_id,
                    "path": str(path),
                    "sha256": sha(path),
                    "offset_sec": offset_samples / 16000,
                    "drift_ppm": 0.0,
                    "snr_db": snr,
                    "gain": gain,
                    "clean_stems": {},
                }
                if source_index == 0:
                    for speaker, stem in individual.items():
                        stem_path = folder / f"clean_{speaker}.wav"
                        sf.write(stem_path, stem * gain, 16000, subtype="FLOAT")
                        source["clean_stems"][speaker] = str(stem_path)
                sources.append(source)
            case = {
                "id": case_id,
                "split": split,
                "condition": condition,
                "device_count": device_count,
                "seed": seed,
                "duration_sec": samples / 16000,
                "speakers": speakers,
                "turns": turns,
                "sources": sources,
                "reference_clock": "canonical_meeting",
                "activity_reference": "source_utterance_extents_not_human_frame_annotations",
                "room": {"dimensions": [6, 4, 2.8], "rt60": PROFILES[condition]["rt60"]},
                "evidence_type": "synthetic_meeting_from_human_transcribed_VIVOS",
            }
            write_json(folder / "recipe.json", case)
            all_cases.append(case)
            log(f"Rendered {case_id} {case['duration_sec']:.1f}s")
    write_json(OUT / "simulation/manifest.json", all_cases)
    write_json(
        OUT / "simulation/protocol.json",
        {
            "seed": SEED,
            "profiles": PROFILES,
            "split_counts": {"development": 3, "validation": 9, "test": 30},
            "source_corpus_manifest_sha256": sha(ROOT / "data/manifests/vivos.jsonl"),
            "enrollment_excluded": True,
            "VIVOS_speaker_disjoint_splits": True,
            "room_renderer": "existing_pyroomacoustics_compute_room_rirs",
            "VAD_reference_limitation": "utterance extents contain internal pauses; VAD boundary scores are synthetic screening, not human frame-level ground truth",
            "no_generated_transcript_labels": True,
            "real_meeting_finetuning_verdict": "requires_human_review_before_training",
        },
    )


def speaker_scenarios():
    import numpy as np
    import soundfile as sf

    original = read_json(OUT / "speaker/manifests.json")
    source_samples = read_json(OUT / "speaker/samples.json")
    records = [
        json.loads(line) for line in (ROOT / "data/manifests/vivos.jsonl").read_text().splitlines()
    ]
    rng = np.random.default_rng(SEED + 50000)
    pools = {}
    samples = {}
    for speaker in sorted({r["speaker_id"] for r in records}):
        eligible = [
            r
            for r in records
            if r["speaker_id"] == speaker and not r["is_enrollment"] and 2 <= r["duration_sec"] <= 8
        ]
        if len(eligible) < 5:
            eligible = [r for r in records if r["speaker_id"] == speaker and not r["is_enrollment"]]
        selected = [eligible[int(i)] for i in rng.choice(len(eligible), 5, replace=False)]
        for condition in PROFILES:
            ids = []
            for row in selected:
                key = f"{row['utterance_id']}__{condition}"
                path = OUT / "speaker_synthetic/audio" / f"{key}.wav"
                if not path.exists():
                    wave, sr = sf.read(ROOT / row["audio_path"], dtype="float32")
                    assert sr == 16000
                    seed = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16)
                    signal = degrade(wave, condition, seed)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    sf.write(path, signal, 16000, subtype="PCM_16")
                samples[key] = {
                    "audio_path": str(path),
                    "speaker": speaker,
                    "file_sha256": sha(path),
                    "origin_id": row["utterance_id"],
                    "condition": condition,
                }
                ids.append(key)
            pools[(speaker, condition)] = ids
    manifests = {}
    for split in ("development", "validation", "test"):
        for condition in PROFILES:
            if split == "development" and condition != "easy":
                continue
            target = ("vivos_" + split) if split != "test" else f"sim_{condition}_test"
            manifests.setdefault(target, [])
            for episode in original[f"vivos_{split}"]:
                e = {**episode, "queries": []}
                for speaker in e["known"] + e["unknown"]:
                    for key in pools[(speaker, condition)]:
                        e["queries"].append(
                            {"id": key, "speaker": speaker, "known": speaker in e["known"]}
                        )
                manifests[target].append(e)
                for ids in e["support"].values():
                    for key in ids:
                        samples[key] = source_samples[key]
    write_json(OUT / "speaker_synthetic/manifests.json", manifests)
    write_json(OUT / "speaker_synthetic/samples.json", samples)
    write_json(
        OUT / "speaker_synthetic/protocol.json",
        {
            "primary_evidence": "synthetic_utterance_queries_with_clean_enrollment",
            "profiles": PROFILES,
            "enrollment_query_disjoint": True,
            "query_origin_ids_disjoint_from_enrollment": True,
            "calibration": "validation_all_three_conditions",
            "test_selection": "frozen_30_episodes_per_K_per_condition",
            "sample_count": len(samples),
            "source_speakers": 65,
            "FT_limit": "read_speech_augmented_acoustics_do_not_represent_spontaneous_meetings",
        },
    )
    log(f"Synthetic speaker corpus ready: {len(samples)} samples")


def main():
    setup()
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["meetings", "speaker"])
    args = parser.parse_args()
    meetings() if args.command == "meetings" else speaker_scenarios()


if __name__ == "__main__":
    main()
