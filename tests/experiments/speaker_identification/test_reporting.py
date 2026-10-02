"""Unit tests for reporting outputs."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from experiments.speaker_identification.contracts import RawPredictionRecord
from experiments.speaker_identification.reporting import (
    generate_classifier_comparison_markdown,
    generate_encoder_screening_markdown,
    save_raw_predictions_csv,
    save_summary_json_and_csv,
)


def test_save_raw_predictions_csv(tmp_path: Path) -> None:
    csv_file = tmp_path / "predictions.csv"
    record = RawPredictionRecord(
        run_id="run-1",
        dataset="vivos",
        split="test",
        protocol="open_set",
        episode_id=0,
        few_shot_k=3,
        encoder_id="E1",
        classifier_id="cosine_prototype",
        query_id="q1",
        true_speaker_id="spk1",
        is_known=True,
        predicted_speaker_id="spk1",
        predicted_unknown=False,
        top1_score=0.85,
        top2_score=0.40,
        margin=0.45,
        score_threshold=0.50,
        margin_threshold=0.10,
        correct=True,
        audio_duration_sec=2.5,
        feature_latency_ms=15.0,
        classifier_latency_ms=0.5,
        end_to_end_latency_ms=15.5,
    )

    save_raw_predictions_csv([record], csv_file)
    assert csv_file.is_file()

    with open(csv_file, newline="", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
        assert len(reader) == 1
        assert len(reader[0]) == 23  # all 23 fields in record
        assert reader[0]["run_id"] == "run-1"
        assert reader[0]["correct"] == "True"


def test_generate_markdown_tables(tmp_path: Path) -> None:
    screening_md = tmp_path / "screening.md"
    comparison_md = tmp_path / "comparison.md"

    row = {
        "dataset": "VIVOS dev",
        "encoder_name": "ECAPA-TDNN",
        "few_shot_k": 3,
        "accuracy_mean": 0.95,
        "accuracy_std": 0.02,
        "macro_precision_mean": 0.94,
        "macro_recall_mean": 0.93,
        "macro_f1_mean": 0.935,
        "macro_f1_std": 0.015,
        "unknown_rejection_mean": 0.90,
        "latency_ms": 18.5,
        "rtf": 0.012,
        "classifier_id": "cosine_prototype",
        "known_accuracy_mean": 0.96,
        "balanced_accuracy_mean": 0.93,
    }

    generate_encoder_screening_markdown([row], screening_md)
    assert screening_md.is_file()
    assert "ECAPA-TDNN" in screening_md.read_text(encoding="utf-8")

    generate_classifier_comparison_markdown([row], comparison_md)
    assert comparison_md.is_file()
    assert "cosine_prototype" in comparison_md.read_text(encoding="utf-8")


def test_save_summary_json_and_csv(tmp_path: Path) -> None:
    j_file = tmp_path / "summary.json"
    c_file = tmp_path / "summary.csv"
    data = [
        {"model": "E1", "k": 3, "f1": 0.92},
        {"model": "E1", "k": 3, "f1": 0.92, "extra_metric": 0.95},
    ]

    save_summary_json_and_csv(data, j_file, c_file)
    assert j_file.is_file()
    assert c_file.is_file()

    loaded = json.loads(j_file.read_text(encoding="utf-8"))
    assert loaded[0]["model"] == "E1"
    with open(c_file, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        assert len(rows) == 2
        assert rows[1]["extra_metric"] == "0.95"
