"""Unit tests for multi-source synchronization and shared VAD segmentation (Milestone 4)."""

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from meeting_pipeline.audio.synchronization import (
    extract_shared_meeting_segments,
    select_reference_source,
    synchronize_multi_source_audio,
)
from meeting_pipeline.domain.contracts import VadConfig
from meeting_pipeline.evaluation.sync_metrics import evaluate_synchronization
from meeting_pipeline.evaluation.vad_metrics import evaluate_vad
from meeting_pipeline.simulation.meeting_recipe import load_recipe


def test_select_reference_source() -> None:
    quiet = np.ones(16000, dtype=np.float32) * 0.001
    loud = np.ones(16000, dtype=np.float32) * 0.1
    sources = {"dev_quiet": quiet, "dev_loud": loud}
    best = select_reference_source(sources)
    assert best == "dev_loud"


def test_synchronization_on_shifted_signals() -> None:
    # Create base signal with distinct bursts
    sr = 16000
    base = np.zeros(sr * 3, dtype=np.float32)
    base[sr : sr + int(sr * 0.5)] = 0.5  # pulse at t=1.0s

    # Shifted signal (delayed by 0.1s = 1600 samples)
    delayed = np.zeros(sr * 3 + 1600, dtype=np.float32)
    delayed[1600 : 1600 + len(base)] = base

    signals = {"ref": base, "dev2": delayed}
    aligned, meta, ref_id = synchronize_multi_source_audio(
        signals, sample_rate=sr, reference_source_id="ref"
    )

    assert ref_id == "ref"
    assert len(aligned["ref"]) == len(aligned["dev2"])
    # Offset should compensate for the 0.1s delay
    assert abs(meta["dev2"]["offset_sec"] - (-0.1)) < 0.05


def test_vad_evaluation_metric() -> None:
    recipe_path = Path("data/generated/smoke/meeting_development_001/recipe.json")
    if not recipe_path.exists():
        pytest.skip("Smoke meeting recipe not found")

    recipe = load_recipe(recipe_path)
    vad_cfg = VadConfig()

    meeting_dir = Path("data/generated/smoke/meeting_development_001")
    audio_signals: dict[str, np.ndarray] = {}
    for dev_id in sorted(recipe.devices.keys()):
        wav_path = meeting_dir / f"{dev_id}.wav"
        data, _ = sf.read(str(wav_path), dtype="float32")
        audio_signals[dev_id] = data

    aligned_signals, _, _ = synchronize_multi_source_audio(audio_signals)
    segments = extract_shared_meeting_segments(aligned_signals, vad_cfg, recipe.meeting_id)

    assert len(segments) > 0
    for s in segments:
        assert s.end_sec > s.start_sec

    # Evaluate VAD
    vad_res = evaluate_vad(segments, recipe)
    assert vad_res["frame_f1"] > 0.85
    assert vad_res["frame_precision"] > 0.80
    assert vad_res["frame_recall"] > 0.80


def test_sync_evaluation_metric() -> None:
    recipe_path = Path("data/generated/smoke/meeting_development_001/recipe.json")
    if not recipe_path.exists():
        pytest.skip("Smoke meeting recipe not found")

    recipe = load_recipe(recipe_path)
    pred_sync = {
        dev_id: {
            "offset_sec": dev_cfg.offset_sec,
            "drift_ppm": dev_cfg.drift_ppm,
        }
        for dev_id, dev_cfg in recipe.devices.items()
    }

    eval_res = evaluate_synchronization(pred_sync, recipe)
    assert eval_res["offset_mae_ms"] < 0.001
    assert eval_res["drift_mae_ppm"] < 0.001
