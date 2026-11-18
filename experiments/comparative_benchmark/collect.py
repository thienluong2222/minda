"""Collect complete research outputs without modifying the application or writing Markdown."""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.comparative_benchmark.common import (
    OUT,
    ROOT,
    SEED,
    read_json,
    setup,
    sha,
    verify_production_unchanged,
    write_csv,
    write_json,
)

SPEAKERS = {"E0": "MFCC", "E1": "ECAPA", "E2": "X-vector", "E3": "WeSpeaker", "E4": "WavLM"}


def optional(path):
    file = OUT / path
    return read_json(file) if file.exists() else []


def collect():
    from experiments.comparative_benchmark.reviews import refresh

    results = {
        "ASR": [
            r
            for f in (OUT / "asr_mps_float16").glob("*/synthetic_test_summary.json")
            for r in read_json(f)
        ],
        "ASR_validation": [
            r
            for f in (OUT / "asr_mps_float16").glob("*/synthetic_validation_summary.json")
            for r in read_json(f)
        ],
        "speaker_encoder_and_classifier": [
            r for f in (OUT / "speaker_synthetic").glob("E*_summary.json") for r in read_json(f)
        ],
        "speaker_clean_reference": [
            r for f in (OUT / "speaker").glob("E*_summary.json") for r in read_json(f)
        ],
        "speaker_clustering": optional("speaker_clustering/summary.json"),
        "activity_and_overlap": [
            r for f in (OUT / "segmentation").glob("*/summary.json") for r in read_json(f)
        ],
        "OCR": [r for f in (OUT / "ocr").glob("*/summary.json") for r in read_json(f)],
        "topic": [r for f in (OUT / "text").glob("*/summary.json") for r in read_json(f)],
        "retrieval": optional("retrieval/summary.json"),
        "separation": [
            r for f in (OUT / "separation").glob("*/summary.json") for r in read_json(f)
        ],
        "fusion_constructed_hypotheses": optional("fusion/summary.json"),
        "fusion_native_diagnostic": optional("fusion_native/summary.json"),
        "core_replay_diagnostic": [
            r for f in (OUT / "core_replay").glob("*/summary.json") for r in read_json(f)
        ],
    }
    for row in results["OCR"]:
        audit = OUT / "ocr" / row["model"] / "charset_audit.json"
        row["eligible_for_full_Vietnamese_orthography"] = (
            not audit.exists() or read_json(audit)["eligible_for_full_Vietnamese_orthography"]
        )
    coverage = {
        "ASR": sorted({r["model"] for r in results["ASR"]}),
        "speaker_encoders": sorted(
            {r["encoder"] for r in results["speaker_encoder_and_classifier"]}
        ),
        "speaker_classifiers": sorted(
            {r["classifier"] for r in results["speaker_encoder_and_classifier"]}
        ),
        "speaker_clusterer_families": sorted(
            {
                "AHC" if r["method"].startswith("ahc_") else r["method"]
                for r in results["speaker_clustering"]
            }
        ),
        "VAD_primary": sorted(
            {
                r["model"]
                for r in results["activity_and_overlap"]
                if r["task"] == "vad" and r["model"] in ("pyannote3", "silero", "crdnn", "fsmn")
            }
        ),
        "local_segmentation_overlap": sorted(
            {r["model"] for r in results["activity_and_overlap"] if r["task"] == "overlap"}
        ),
        "OCR_eligible": sorted(
            {r["model"] for r in results["OCR"] if r["eligible_for_full_Vietnamese_orthography"]}
        ),
        "text_encoders": sorted({r["encoder"] for r in results["topic"]}),
        "topic_clusterers": sorted({r["clusterer"] for r in results["topic"]}),
        "retrieval": sorted({r["method"] for r in results["retrieval"]}),
        "separation": sorted({r["model"] for r in results["separation"]}),
        "fusion": sorted({r["method"] for r in results["fusion_constructed_hypotheses"]}),
    }
    assert all(len(models) >= 4 for models in coverage.values()), coverage
    flat = []
    metrics = (
        "wer",
        "cer",
        "macro_f1",
        "accuracy",
        "closed_set_accuracy",
        "unknown_rejection",
        "false_accept_rate",
        "f1",
        "precision",
        "recall",
        "ari",
        "nmi",
        "bcubed_f1",
        "si_sdr_improvement_db",
        "negative_improvement_rate",
        "rtf",
        "hit_at_2",
        "recall_at_2",
        "mrr",
        "collapse_rate",
        "oracle_k4_ari_diagnostic",
        "der_with_overlap",
        "der_without_overlap",
    )
    for task, rows in results.items():
        for row in rows:
            for metric in metrics:
                if row.get(metric) is not None:
                    flat.append(
                        {
                            "task": task,
                            "model": row.get("model", row.get("encoder", "")),
                            "method": row.get(
                                "method", row.get("classifier", row.get("clusterer", ""))
                            ),
                            "split": row.get("split", "test"),
                            "condition": row.get(
                                "condition", row.get("dataset", row.get("case", "all"))
                            ),
                            "activity_task": row.get("task", ""),
                            "k": row.get("k", ""),
                            "metric": metric,
                            "value": row[metric],
                            "eligible": row.get("eligible_for_full_Vietnamese_orthography", True),
                        }
                    )
    write_csv(OUT / "summary.csv", flat)
    report = {
        "title": "Non-LLM pipeline synthetic comparative screening",
        "seed": SEED,
        "baseline": {
            "implementation": "web_app/src/meeting_pipeline",
            "ASR": "PhoWhisper-medium",
            "speaker": "ECAPA+cosine_prototype",
            "speaker_clustering": "constrained_AHC_cosine_threshold_0.4",
            "segmentation": "pyannote/segmentation-3.0",
            "fusion": "F5_RULE_WEIGHTED_CORRECTED",
            "text": "multilingual-e5-small+FCM",
            "OCR": "Tesseract_tessdata_fast_vie+eng",
            "retrieval": "BM25",
            "separation": "sepformer-whamr_available_but_overlap_branch_skipped",
        },
        "coverage": coverage,
        "integrity": verify_production_unchanged(),
        "methodology": {
            "meeting_counts": {"development": 3, "validation": 9, "test": 30},
            "audio": "VIVOS natural Vietnamese utterances placed in simulated rooms; no TTS or LLM",
            "acoustics": "RT60 0.12/0.30/0.55 sec, SNR 25/15/5 dB, 1/2/4 microphones; stress clipping",
            "speaker_splits": "development/validation/test speakers disjoint; enrollment and query origins disjoint",
            "selection": "classifier C/K selected on development; rejection thresholds and clusterer parameters selected on validation; frozen test",
            "ASR": "5 real checkpoints, same 30 non-overlap simulated turn clips plus 30 matched clean controls; primary condition simulated_only",
            "ASR_runtime": "MPS float16 on 16GB Apple M4; each model separate process; partial CPU/FP32 runs excluded",
            "speaker": "5 encoders x 4 classifiers x enrollment K=1,3,5; repeated shared episodes; unknown speakers included",
            "uncertainty": "paired bootstrap by actual source speaker; repeated episodes not treated as independent speakers",
            "topic": "4 encoders x 4 clusterers, 30 held-out-template test documents; labels known by construction",
            "OCR": "same rendered line crops, 30 held-out strings x 3 conditions plus blank controls; no page layout benchmark",
            "separation": "4 real checkpoints, 20 test mixtures at 8kHz, permutation-invariant SI-SDR improvement against reverberant stems",
            "fusion": "7 methods; main 30-meeting script-corruption test plus 3 native-pipeline-meeting diagnostic",
            "finetuning": "No pretrained model weights updated; experimental classifiers and rejection thresholds fitted only in reports",
        },
        "limitations": [
            "Synthetic screening cannot establish the best model for unobserved real meetings or prove that fine-tuning is required.",
            "VIVOS test speakers are held out from this experiment, not necessarily from upstream checkpoint training; public-model training contamination is unknown.",
            "Only 30 non-overlap simulated ASR clips from 13 actual source speakers; validation has 9 clips and 83 reference words.",
            "All ASR paired 95% delta intervals against medium include zero on this sample.",
            "Utterance-extent activity labels include internal silence; dry-source-energy sensitivity analysis changes overlap ranking.",
            "Diarization clustering uses oracle turn boundaries; full native-pipeline replay is only a three-meeting diagnostic.",
            "Short simulated mixtures have at most two concurrent speakers; no clock drift, spontaneous conversational disfluency, or real page scans.",
            "Text topics and retrieval relevance are scripted proxies; retrieval labels do not establish factual entailment.",
            "Paddle latin PP-OCRv5 checkpoint lacks required Vietnamese output characters and is excluded from qualified OCR ranking.",
            "Application intentionally skips overlap separation/ASR/identity; separator gains cannot improve that branch without a future pipeline change.",
        ],
        "results": results,
        "paired_comparisons": optional("paired_comparisons.json"),
        "ASR_error_analysis": optional("ASR_error_analysis.json"),
        "reference_sensitivity": optional("reference_diagnostics.json"),
        "finetuning_reviews": refresh(),
        "pretrained_model_inventory": optional("model_inventory.json"),
        "extra_model_inventory": optional("extra_model_inventory.json"),
    }
    assert report["integrity"]["passed"]
    write_json(OUT / "summary.json", report)
    return report


def plot(report):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    r = report["results"]
    panels = [
        (
            "ASR simulated WER (lower)",
            [x for x in r["ASR"] if x["condition"] == "simulated_only"],
            "model",
            "wer",
            "phowhisper_medium",
        ),
        (
            "Speaker stress macro F1 (higher)",
            [
                x
                for x in r["speaker_encoder_and_classifier"]
                if x["dataset"] == "sim_stress_test"
                and x["classifier"] == "cosine_prototype"
                and x["k"] == 3
            ],
            "encoder",
            "macro_f1",
            "E1",
        ),
        (
            "VAD F1, extent proxy (higher)",
            [
                x
                for x in r["activity_and_overlap"]
                if x["task"] == "vad"
                and x["condition"] == "all"
                and x["model"] in ("pyannote3", "silero", "crdnn", "fsmn")
            ],
            "model",
            "f1",
            "pyannote3",
        ),
        (
            "Overlap F1, extent proxy (higher)",
            [
                x
                for x in r["activity_and_overlap"]
                if x["task"] == "overlap" and x["condition"] == "all"
            ],
            "model",
            "f1",
            "pyannote3",
        ),
        (
            "OCR line CER (lower)",
            [
                x
                for x in r["OCR"]
                if x["condition"] == "all" and x["eligible_for_full_Vietnamese_orthography"]
            ],
            "model",
            "cer",
            "tesseract_fast",
        ),
        (
            "Topic ARI with same FCM (higher)",
            [x for x in r["topic"] if x["split"] == "test" and x["clusterer"] == "fcm"],
            "encoder",
            "ari",
            "e5_small",
        ),
    ]
    fig, axes = plt.subplots(2, 3, figsize=(15, 9), constrained_layout=True)
    for ax, (title, rows, label, metric, baseline) in zip(axes.flat, panels, strict=True):
        rows = sorted(rows, key=lambda x: x[label])
        names = [
            SPEAKERS.get(x[label], x[label])
            .replace("phowhisper_", "Pho-")
            .replace("tesseract_", "Tess-")
            .replace("vietocr_", "VietOCR-")
            for x in rows
        ]
        values = [x[metric] for x in rows]
        ax.barh(
            names, values, color=["#ce6a28" if x[label] == baseline else "#3576ad" for x in rows]
        )
        for i, value in enumerate(values):
            ax.text(value + max(values) * 0.025, i, f"{value:.3f}", va="center", fontsize=9)
        ax.set_xlim(0, max(values) * 1.24)
        ax.set_title(title, fontsize=12)
        ax.grid(axis="x", alpha=0.2)
        ax.set_axisbelow(True)
        ax.invert_yaxis()
    fig.suptitle(
        "Synthetic screening | orange = current model | test points, not real-meeting guarantees",
        fontsize=15,
    )
    fig.savefig(OUT / "benchmark_overview.png", dpi=180)
    plt.close(fig)


def environment():
    import importlib.metadata

    packages = {}
    imported = {}
    for name in (".venv", ".venv-benchmark"):
        output = subprocess.check_output(
            [
                str(ROOT / name / "bin/python"),
                "-c",
                "import importlib.metadata as m,json; print(json.dumps(sorted({d.metadata['Name']+'=='+d.version for d in m.distributions()})))",
            ],
            text=True,
        )
        packages[name] = json.loads(output)
        output = subprocess.check_output(
            [
                str(ROOT / name / "bin/python"),
                "-c",
                "import numpy,torch,transformers,json; print(json.dumps({m.__name__:{'version':m.__version__,'file':m.__file__} for m in (numpy,torch,transformers)}))",
            ],
            text=True,
        )
        imported[name] = json.loads(output)
    baseline_packages = read_json(OUT / "baseline_manifest.json")["packages"]
    changed = {
        name: {"before": version, "after": importlib.metadata.version(name)}
        for name, version in baseline_packages.items()
        if importlib.metadata.version(name) != version
    }
    files = {
        str(p.relative_to(ROOT)): sha(p)
        for p in (ROOT / "experiments/comparative_benchmark").glob("*.py")
    }
    revision = subprocess.check_output(
        ["git", "-C", str(OUT / "runtime/DiariZen"), "rev-parse", "HEAD"], text=True
    ).strip()
    write_json(
        OUT / "reproducibility.json",
        {
            "platform": platform.platform(),
            "python": sys.version,
            "packages": packages,
            "actual_imports": imported,
            "original_environment_changed_packages": changed,
            "benchmark_source_sha256": files,
            "DiariZen_source_revision": revision,
            "baseline_snapshot": str(OUT / "frozen_source.zip"),
        },
    )


if __name__ == "__main__":
    setup()
    result = collect()
    plot(result)
    environment()
    print(json.dumps({key: len(value) for key, value in result["coverage"].items()}))
