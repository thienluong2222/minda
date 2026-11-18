"""Consolidate measured engineering results without inventing long-recording timings."""

import hashlib
import json
from pathlib import Path


def main():
    import yaml

    root = Path(__file__).resolve().parents[2]
    output = root / "reports/pipeline_speed/20261109"

    def read(path):
        return json.loads(path.read_text())

    old_asr = read(
        root
        / "reports/comparative_benchmark/20261104"
        / "asr_mps_float16/phowhisper_medium/synthetic_test_summary.json"
    )
    old_asr = next(r for r in old_asr if r["condition"] == "all")
    new_asr = read(output / "asr/mlx_window_test_summary.json")
    history = {
        name: read(output / name / "speed_summary.json") for name in ("contract_v2", "batch2")
    }
    full = read(output / "end_to_end/summary.json")
    run = Path(full["run"])
    report = read(run / "minutes/model_report.json")
    code = {}
    for directory in [
        root / "web_app/src/meeting_pipeline/minutes",
        root / "web_app/src/meeting_pipeline/adapters",
        root / "web_app/scripts",
    ]:
        for path in directory.glob("*.py"):
            code[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    result = {
        "scope": "Engineering measurements on existing synthetic data; no human validation.",
        "asr_test": {
            "previous_MPS": {
                k: old_asr[k] for k in ["rtf", "wer", "inference_seconds", "audio_seconds"]
            },
            "selected_MLX": new_asr,
            "historical_speed_ratio": old_asr["inference_seconds"]
            / new_asr["seconds_including_load"],
        },
        "asr_validation": read(output / "asr/mlx_window_v2_validation_summary.json"),
        "graph_engineering_history": history,
        "end_to_end": {
            **full,
            "graph_wall_sec": report["wall_sec"],
            "source_fallback_rate": report["coverage"]["source_fallback_rate"],
            "claim_id_coverage_complete": report["coverage"]["claim_id_coverage_complete"],
        },
        "linear_two_hour_extrapolation_hours": full["total_wall_sec"] / full["input_audio_sec"] * 2,
        "two_hour_end_to_end_measured": False,
        "semantic_accuracy_verified": False,
        "defaults": {
            "audio": yaml.safe_load((root / "web_app/configs/default.yaml").read_text())["asr"],
            "minutes": yaml.safe_load((root / "web_app/configs/minutes.yaml").read_text()),
        },
        "source_sha256": code,
        "tests": {
            "broad_web_unit_and_graph_API": 417,
            "broad_root_unit": 270,
            "final_graph_and_speed_regressions": 50,
        },
        "limitations": [
            "Historical speed ratios are not controlled repeated A/B experiments.",
            "Word timing checks are structural; there are no manually corrected word timestamps.",
            "Graph ID coverage does not prove semantic completeness or secretary-style quality.",
            "Presentation budgeting and selective correction remain off by default.",
            "GPU batch 2 was slower in this probe; default remains batch 1.",
        ],
    }
    (output / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(
        json.dumps(
            {
                "asr_speed_ratio": result["asr_test"]["historical_speed_ratio"],
                "total_wall_sec": full["total_wall_sec"],
                "two_hour_linear_hours": result["linear_two_hour_extrapolation_hours"],
            }
        )
    )


if __name__ == "__main__":
    main()
