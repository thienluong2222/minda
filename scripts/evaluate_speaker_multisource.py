"""Replay speaker decisions from aligned audio and saved turns, without ASR."""

from __future__ import annotations

import argparse
import hashlib
import json
import resource
import time
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from meeting_pipeline.adapters.pyannote_segmentation import PyannoteSegmentationAdapter
from meeting_pipeline.application.speakers import SpeakerProfileInput, SpeakerRegistry
from meeting_pipeline.config import load_config
from meeting_pipeline.pipeline.speaker_turns import (
    SpeakerTurn,
    SpeakerTurnDetector,
    source_activity_for_turn,
)
from meeting_pipeline.speaker.clustering import GlobalSpeakerClusterer
from meeting_pipeline.speaker.encoder import create_speaker_encoder
from meeting_pipeline.speaker.source_quality import SpeakerFusionPolicy


class CachedEncoder:
    """Cache real encoder output by waveform bytes and pinned encoder identity."""

    def __init__(self, encoder: Any, root: Path, identity: str) -> None:
        self.encoder = encoder
        self.root = root
        self.identity = identity
        self.root.mkdir(parents=True, exist_ok=True)
        self.hits = 0
        self.misses = 0

    def encode(self, waveform: np.ndarray) -> np.ndarray:
        digest = hashlib.sha256(self.identity.encode() + waveform.tobytes()).hexdigest()
        path = self.root / f"{digest}.npy"
        if path.is_file():
            self.hits += 1
            return np.asarray(np.load(path), dtype=np.float32)
        self.misses += 1
        result = np.asarray(self.encoder.encode(waveform), dtype=np.float32)
        np.save(path, result)
        return result


def _reference_label(turn: SpeakerTurn, reference: list[dict[str, Any]]) -> str | None:
    # Reference is used only after inference for evaluation, never passed to the clusterer.
    overlaps = [
        (
            max(0.0, min(turn.end_sec, row["end_sec"]) - max(turn.start_sec, row["start_sec"])),
            str(row["reference_speaker_id"]),
        )
        for row in reference
    ]
    if not overlaps:
        return None
    duration, label = max(overlaps)
    return label if duration >= 0.5 * (turn.end_sec - turn.start_sec) else None


def _pairwise_f1(labels: list[str], predicted: list[str]) -> dict[str, float]:
    tp = fp = fn = 0
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            truth = labels[i] == labels[j]
            guess = predicted[i] == predicted[j]
            tp += int(truth and guess)
            fp += int(not truth and guess)
            fn += int(truth and not guess)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--profiles", choices=["none", "partial", "full"], default="none")
    parser.add_argument("--enrollment-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--ablation",
        choices=["none", "snr", "duration", "clipping", "dropout", "purity"],
        default="none",
    )
    args = parser.parse_args()
    run = args.run.resolve()
    config = load_config(Path("configs/default.yaml"))
    manifest = json.loads((run / "manifest.json").read_text())
    ids = manifest.get("speaker_profiles", [])
    if args.profiles == "none":
        ids = []
    elif args.profiles == "partial":
        ids = ids[:1]
    turns = [
        SpeakerTurn(**row) for row in json.loads((run / "speaker_turns.json").read_text())["turns"]
    ]
    aligned = {
        p.stem: sf.read(p, dtype="float32")[0] for p in sorted((run / "aligned").glob("*.wav"))
    }
    sync_doc = json.loads((run / "sync_metadata.json").read_text())
    sync_metadata = sync_doc["sources"]
    for sid, row in sync_metadata.items():
        if "valid_coverage_interval" not in row:
            duration = sf.info(run / "decoded" / f"{sid}.wav").duration
            start = max(0.0, float(row.get("offset_sec", 0.0)))
            end = min(len(aligned[sid]) / 16000, start + duration)
            row["valid_coverage_interval"] = [start, end]
        if sid == sync_doc["reference_source_id"]:
            row["status"] = "reference"
    if any(not turn.source_activity for turn in turns):
        adapter = PyannoteSegmentationAdapter(Path("unused"))
        detector = SpeakerTurnDetector(Path("unused"), 2.5, adapter)
        num_bins = max(1, int(np.ceil(max(len(sig) for sig in aligned.values()) / 800)))
        matrices = {
            sid: detector._decode(adapter.load_npz(run / "segmentation" / f"{sid}.npz"), num_bins)
            for sid in aligned
        }
        for turn in turns:
            turn.source_activity = {
                sid: source_activity_for_turn(matrix, turn.start_sec, turn.end_sec, 0.05)
                for sid, matrix in matrices.items()
            }
    encoder_id = f"{config.identity['model_id']}@{config.identity['model_revision']}"
    encoder = CachedEncoder(
        create_speaker_encoder(
            model_id=str(config.identity["model_id"]),
            revision=str(config.identity["model_revision"]),
            cache_dir=config.paths.model_cache_dir,
        ),
        config.paths.data_dir / "evaluations" / "embedding_cache",
        encoder_id,
    )
    if args.enrollment_dir and args.profiles != "none":
        sample_paths = sorted(args.enrollment_dir.glob("*.wav"))
        if args.profiles == "partial":
            sample_paths = sample_paths[:1]
        profiles = []
        for sample_path in sample_paths:
            waveform, rate = sf.read(sample_path, dtype="float32")
            if rate != 16000:
                raise ValueError(f"Unexpected enrollment rate: {sample_path}")
            profiles.append(SpeakerProfileInput(
                sample_path.stem, sample_path.stem, encoder.encode(waveform)
            ))
    elif manifest.get("source_meeting") and args.profiles != "none":
        recipe = json.loads((Path(manifest["source_meeting"]) / "recipe.json").read_text())
        enrollments = list(recipe["enrollment_utterances"].items())
        if args.profiles == "partial":
            enrollments = enrollments[:1]
        profiles = []
        vivos_root = Path("data/external/vivos/extracted/vivos")
        for speaker_id, utterances in enrollments:
            vectors = []
            for utterance in utterances[:2]:
                found = list(vivos_root.glob(f"*/waves/{speaker_id}/{utterance}.wav"))
                if not found:
                    raise FileNotFoundError(utterance)
                waveform, rate = sf.read(found[0], dtype="float32")
                if rate != 16000:
                    raise ValueError(f"Unexpected enrollment rate: {found[0]}")
                vectors.append(encoder.encode(waveform))
            prototype = np.mean(np.stack(vectors), axis=0)
            prototype /= max(float(np.linalg.norm(prototype)), 1e-8)
            profiles.append(SpeakerProfileInput(speaker_id, speaker_id, prototype))
    else:
        profiles = SpeakerRegistry(config).load(ids)
    report: dict[str, Any] = {
        "run": str(run),
        "encoder": encoder_id,
        "profiles": args.profiles,
        "ablation": args.ablation,
        "source_count": len(aligned),
        "duration_sec": max(len(signal) for signal in aligned.values()) / 16000,
        "data_split": json.loads(
            (Path(manifest["source_meeting"]) / "recipe.json").read_text()
        ).get("split")
        if manifest.get("source_meeting")
        else "fpt_diagnostic",
        "input_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((run / "aligned").glob("*.wav"))
        },
        "profile_ids": [profile.speaker_id for profile in profiles],
        "thresholds": {
            "cluster_distance": 0.40, "assign_similarity": 0.35,
            "assign_margin": 0.05, "profile_score": 0.25, "profile_margin": 0.05,
        },
        "calibration_status": "unvalidated",
        "speaker_only": True,
        "policies": {},
    }
    enrolled_labels = {profile.display_name.casefold(): profile.speaker_id for profile in profiles}
    for policy in SpeakerFusionPolicy:
        started = time.perf_counter()
        hits_before, misses_before = encoder.hits, encoder.misses
        clusterer = GlobalSpeakerClusterer(
            encoder,
            fusion_policy=policy,
            enrolled_match_threshold=0.25,
            enrolled_margin=0.05,
            ablate_quality_feature=None if args.ablation == "none" else args.ablation,
        )
        assignments, _, summary = clusterer.cluster_and_identify(
            turns, aligned, 16000, profiles, sync_metadata=sync_metadata
        )
        speaker_stage_seconds = time.perf_counter() - started
        # Reference is intentionally unavailable until this policy has made its decisions.
        reference = json.loads(args.reference.read_text()) if args.reference else []
        rows = [(turn, assignments[turn.turn_id]) for turn in turns if turn.speaker_count == 1]
        measured = [
            (label, item.meeting_speaker_id)
            for turn, item in rows
            if (label := _reference_label(turn, reference)) and item.meeting_speaker_id
        ]
        labeled = [
            (label, item) for turn, item in rows if (label := _reference_label(turn, reference))
        ]
        known = [(label, item) for label, item in labeled if label.casefold() in enrolled_labels]
        unknown = [
            (label, item) for label, item in labeled if label.casefold() not in enrolled_labels
        ]
        gated: dict[str, int] = {}
        for _, item in rows:
            for evidence in item.source_evidence:
                reason = evidence.get("exclusion_reason")
                if reason:
                    gated[str(reason)] = gated.get(str(reason), 0) + 1
        report["policies"][policy.value] = {
            "clusters": summary["total_clusters"],
            "ambiguous_turns": sum(item.speaker_status == "ambiguous" for _, item in rows),
            "speaker_stage_wall_seconds": round(speaker_stage_seconds, 3),
            "embedding_cache_hits": encoder.hits - hits_before,
            "embedding_cache_misses": encoder.misses - misses_before,
            "process_peak_rss_raw": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "labeled_turns": len(labeled),
            "evaluated_turns": len(measured),
            "known_id_accuracy": (
                sum(item.speaker_id == enrolled_labels[label.casefold()] for label, item in known)
                / len(known)
                if known
                else None
            ),
            "unknown_false_accept_rate": (
                sum(item.speaker_status == "identified" for _, item in unknown) / len(unknown)
                if unknown
                else None
            ),
            "unknown_recall": (
                sum(item.speaker_status == "unknown" for _, item in unknown) / len(unknown)
                if unknown
                else None
            ),
            "gated_sources_by_reason": gated,
            "short_turns": sum(
                turn.end_sec - turn.start_sec < 1.5 for turn, _ in rows
            ),
            "short_ambiguous": sum(
                turn.end_sec - turn.start_sec < 1.5 and item.speaker_status == "ambiguous"
                for turn, item in rows
            ),
            "long_turns": sum(
                turn.end_sec - turn.start_sec >= 1.5 for turn, _ in rows
            ),
            "long_ambiguous": sum(
                turn.end_sec - turn.start_sec >= 1.5 and item.speaker_status == "ambiguous"
                for turn, item in rows
            ),
            "pairwise": _pairwise_f1([row[0] for row in measured], [row[1] for row in measured])
            if reference
            else None,
            "assignments": [item.as_dict() for _, item in rows],
        }
    target = (
        args.output
        or config.paths.data_dir
        / "evaluations"
        / f"{run.name}-{args.profiles}-{args.ablation}.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(target)
    for policy, row in report["policies"].items():
        print(
            policy,
            row["clusters"],
            row["ambiguous_turns"],
            row["pairwise"],
            row["speaker_stage_wall_seconds"],
        )


if __name__ == "__main__":
    main()
