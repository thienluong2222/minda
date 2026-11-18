"""Replay seven fusion algorithms on identical native pipeline ASR hypotheses."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.comparative_benchmark.common import OUT, read_json, setup, write_csv, write_json


def run():
    import jiwer

    from meeting_pipeline.data.vivos import normalize_vietnamese_text
    from meeting_pipeline.domain.contracts import SourceHypothesis
    from meeting_pipeline.fusion.confusion_network import build_confusion_network
    from meeting_pipeline.fusion.model import LearnedFusionModel
    from meeting_pipeline.pipeline.multi_source_fusion import MultiSourceFusionPipeline

    model = LearnedFusionModel.load(OUT / "fusion/learned_fusion_model.joblib")
    methods = (
        "F0_FIXED",
        "F1_BEST_SEGMENT",
        "F3_ROVER",
        "F4_ASR_WEIGHTED",
        "F5_RULE_WEIGHTED",
        "F5_RULE_WEIGHTED_CORRECTED",
        "F6_LEARNED",
    )
    cases = {r["id"]: r for r in read_json(OUT / "simulation/manifest.json")}
    predictions = []
    for row in read_json(OUT / "core_replay/baseline/summary.json"):
        run_dir = Path(row["run_dir"])
        reference_source = read_json(run_dir / "sync_metadata.json")["reference_source_id"]
        texts = {method: [] for method in methods}
        hypotheses = read_json(run_dir / "source_hypotheses.json")["segments"]
        active_segments = 0
        for segment in hypotheses:
            sources = {
                sid: SourceHypothesis.model_validate(data)
                for sid, data in segment["sources"].items()
            }
            active_segments += bool(sources)
            bins = build_confusion_network(sources)
            for method in methods:
                fused, _ = MultiSourceFusionPipeline._fuse(
                    method, sources, bins, model, reference_source
                )
                texts[method].append(fused)
        reference = normalize_vietnamese_text(
            " ".join(turn["reference"] for turn in cases[row["case"]]["turns"])
        )
        for method, parts in texts.items():
            text = normalize_vietnamese_text(" ".join(parts))
            score = jiwer.process_words(reference, text)
            predictions.append(
                {
                    "case": row["case"],
                    "condition": row["condition"],
                    "method": method,
                    "reference": reference,
                    "prediction": text,
                    "wer": score.wer,
                    "active_segments": active_segments,
                }
            )
    summary = []
    for method in methods:
        selected = [r for r in predictions if r["method"] == method]
        summary.append(
            {
                "method": method,
                "meetings": len(selected),
                "wer": jiwer.wer(
                    [r["reference"] for r in selected], [r["prediction"] for r in selected]
                ),
                "scope": "three_native_pipeline_simulated_meetings_diagnostic_only",
                "F6_training_scope": "scripted_corruptions_development_only_not_actual_ASR",
            }
        )
    write_json(OUT / "fusion_native/summary.json", summary)
    write_json(OUT / "fusion_native/predictions.json", predictions)
    write_csv(OUT / "fusion_native/summary.csv", summary)


if __name__ == "__main__":
    setup()
    run()
