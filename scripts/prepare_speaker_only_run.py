"""Build ignored speaker-only artifacts from a generated VIVOS multi-device meeting."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf

from meeting_pipeline.adapters.pyannote_segmentation import PyannoteSegmentationAdapter
from meeting_pipeline.audio.synchronization import synchronize_multi_source_audio
from meeting_pipeline.config import load_config
from meeting_pipeline.domain.contracts import VadConfig
from meeting_pipeline.pipeline.speaker_turns import SpeakerTurnDetector
from meeting_pipeline.pipeline.stages.shared_segmentation import run_shared_pyannote_segmentation


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("meeting_dir", type=Path)
    args = parser.parse_args()
    source_dir = args.meeting_dir.resolve()
    config = load_config(Path("configs/default.yaml"))
    output = config.paths.data_dir / "evaluations" / "speaker_only_runs" / source_dir.name
    decoded_dir = output / "decoded"
    aligned_dir = output / "aligned"
    decoded_dir.mkdir(parents=True, exist_ok=True)
    aligned_dir.mkdir(parents=True, exist_ok=True)
    decoded = {}
    for index, path in enumerate(sorted(source_dir.glob("device_*.wav")), start=1):
        signal, rate = sf.read(path, dtype="float32")
        if rate != 16000 or signal.ndim != 1:
            raise ValueError(f"Expected 16 kHz mono: {path}")
        sid = f"source-{index}"
        decoded[sid] = np.asarray(signal, dtype=np.float32)
        sf.write(decoded_dir / f"{sid}.wav", signal, rate)
    aligned, sync, reference = synchronize_multi_source_audio(decoded, 16000)
    aligned_paths = {}
    for sid, signal in aligned.items():
        path = aligned_dir / f"{sid}.wav"
        sf.write(path, signal, 16000)
        aligned_paths[sid] = path
    duration = max(len(signal) for signal in aligned.values()) / 16000
    checkpoint = (
        config.paths.model_cache_dir
        / "models--pyannote--segmentation-3.0"
        / "snapshots"
        / str(config.models["segmentation_revision"])
        / "pytorch_model.bin"
    )
    adapter = PyannoteSegmentationAdapter(checkpoint, config.segmentation.step_seconds)
    vad = VadConfig(
        threshold=config.segmentation.vad_threshold,
        min_speech_sec=config.segmentation.minimum_speech_ms / 1000,
        merge_gap_sec=config.segmentation.merge_gap_ms / 1000,
        padding_sec=config.segmentation.speech_pad_ms / 1000,
        max_segment_sec=15.0,
    )
    segments, cached = run_shared_pyannote_segmentation(
        aligned_paths,
        adapter,
        duration,
        vad,
        source_dir.name,
        sync_metadata=sync,
        run_dir=output,
    )
    detector = SpeakerTurnDetector(checkpoint, config.segmentation.step_seconds, adapter)
    turns = detector.detect(
        aligned_paths, segments, reference, duration,
        cached_results=cached, sync_metadata=sync,
    )
    (output / "sync_metadata.json").write_text(
        json.dumps(
            {
                "schema_version": "2.0",
                "reference_source_id": reference,
                "sources": sync,
            },
            indent=2,
        )
    )
    (output / "speaker_turns.json").write_text(
        json.dumps(
            {
                "schema_version": "2.0",
                "turns": [turn.as_dict() for turn in turns],
            },
            indent=2,
        )
    )
    (output / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "2.0",
                "speaker_profiles": [],
                "source_meeting": str(source_dir),
                "vad_backend": "pyannote_shared",
            },
            indent=2,
        )
    )
    print(f"{output}: {len(turns)} turns, {len(aligned)} sources")


if __name__ == "__main__":
    main()
