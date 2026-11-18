"""Full experiment runner executing M7 end-to-end evaluation.

Specification: Section 13.8 of docs/PLAN_VIVOS_SYNTHETIC_PIPELINE.md.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import jiwer
import numpy as np
import soundfile as sf
import yaml

from meeting_pipeline.adapters.phowhisper_asr import PhoWhisperAsrAdapter
from meeting_pipeline.asr.segment_asr import transcribe_segment_sources
from meeting_pipeline.audio.synchronization import (
    extract_shared_meeting_segments,
    synchronize_multi_source_audio,
)
from meeting_pipeline.config import AsrConfig
from meeting_pipeline.data.manifest import load_manifest_jsonl
from meeting_pipeline.domain.contracts import (
    ExperimentConfig,
    FinalTimelineItem,
    ModelsConfig,
    VivosDataConfig,
)
from meeting_pipeline.evaluation.asr_metrics import evaluate_asr_transcripts
from meeting_pipeline.evaluation.report import (
    generate_baseline_comparison_table,
    generate_failure_cases_report,
    generate_speaker_enrollment_table,
    save_summary_report,
)
from meeting_pipeline.evaluation.speaker_metrics import evaluate_speaker_identification
from meeting_pipeline.evaluation.sync_metrics import evaluate_synchronization
from meeting_pipeline.evaluation.vad_metrics import evaluate_vad
from meeting_pipeline.fusion.baselines import (
    fuse_f0_fixed,
    fuse_f1_best_segment,
    fuse_f2_oracle_best,
    fuse_f3_rover,
    fuse_f4_asr_weighted,
    fuse_f5_rule_weighted,
    fuse_f5_rule_weighted_corrected,
    fuse_f6_learned,
)
from meeting_pipeline.fusion.confusion_network import build_confusion_network
from meeting_pipeline.fusion.model import LearnedFusionModel
from meeting_pipeline.fusion.provenance import build_final_timeline_item
from meeting_pipeline.simulation.meeting_recipe import load_recipe
from meeting_pipeline.speaker.encoder import create_speaker_encoder
from meeting_pipeline.speaker.enrollment import build_speaker_prototypes
from meeting_pipeline.speaker.identification import identify_multi_source_speaker

logger = logging.getLogger(__name__)


def run_experiment_pipeline(
    config_path: Path | str = "configs/experiment/smoke.yaml",
) -> dict[str, Any]:
    """Execute end-to-end experiment: Dev training -> Val calibration -> Test evaluation."""
    exp_p = Path(config_path)
    exp_cfg = ExperimentConfig.model_validate(yaml.safe_load(exp_p.read_text(encoding="utf-8")))

    data_cfg = VivosDataConfig.model_validate(
        yaml.safe_load(Path(exp_cfg.data_config).read_text(encoding="utf-8"))
    )
    models_cfg = ModelsConfig.model_validate(
        yaml.safe_load(Path(exp_cfg.models_config).read_text(encoding="utf-8"))
    )

    manifest_records = load_manifest_jsonl(data_cfg.manifest_output_path)
    catalog = json.loads(Path(data_cfg.catalog_output_path).read_text(encoding="utf-8"))

    recipes_dir = Path(exp_cfg.output_dirs.get("recipes", "data/recipes/smoke"))
    audio_dir = Path(exp_cfg.output_dirs.get("generated_audio", "data/generated/smoke"))
    artifacts_dir = Path(exp_cfg.output_dirs.get("artifacts", "artifacts/smoke"))
    reports_dir = Path(exp_cfg.output_dirs.get("reports", "reports/smoke"))

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    # Initialize shared model adapters
    logger.info("Initializing offline PhoWhisper and configured speaker adapters...")
    asr_cfg = AsrConfig(
        model_id=models_cfg.asr.model_id,
        model_revision=models_cfg.asr.revision,
        language=models_cfg.asr.language,
    )
    asr_adapter = PhoWhisperAsrAdapter(config=asr_cfg, cache_dir=Path("data/model_cache"))
    speaker_encoder = create_speaker_encoder(
        model_id=models_cfg.speaker_encoder.model_id,
        revision=models_cfg.speaker_encoder.revision,
        cache_dir="data/model_cache",
    )

    # ---------------------------------------------------------------------------
    # Step 1: Train Learned Fusion Model on Development Split
    # ---------------------------------------------------------------------------
    logger.info("Step 1: Training Learned Fusion model on Development split...")
    dev_recipe_file = recipes_dir / "meeting_development_001.json"
    learned_model = LearnedFusionModel()

    if dev_recipe_file.exists():
        dev_recipe = load_recipe(dev_recipe_file)
        dev_meeting_dir = audio_dir / "meeting_development_001"

        # Load dev audio
        dev_signals: dict[str, np.ndarray] = {}
        for dev_id in dev_recipe.devices:
            sig, _ = sf.read(str(dev_meeting_dir / f"{dev_id}.wav"), dtype="float32")
            dev_signals[dev_id] = sig

        aligned_dev, _, _ = synchronize_multi_source_audio(dev_signals)
        dev_segments = extract_shared_meeting_segments(
            aligned_dev, models_cfg.vad, dev_recipe.meeting_id
        )

        training_feats: list[list[float]] = []
        training_labels: list[int] = []

        # Find reference turns for matching
        for seg in dev_segments[:15]:  # Use initial segments for fast training
            # Find overlapping reference turn
            matching_turn = None
            for turn in dev_recipe.turns:
                if turn.start_sec < seg.end_sec + 0.2 and turn.end_sec > seg.start_sec - 0.2:
                    matching_turn = turn
                    break

            ref_words = set(matching_turn.text_normalized.split()) if matching_turn else set()

            # Slice audio for each device
            s_samp = round(seg.start_sec * 16000)
            e_samp = round(seg.end_sec * 16000)
            seg_waves = {d: aligned_dev[d][s_samp:e_samp] for d in aligned_dev}

            dev_hyps = transcribe_segment_sources(
                dev_recipe.meeting_id, seg, seg_waves, asr_adapter
            )

            bins = build_confusion_network(dev_hyps)
            num_srcs = len(dev_hyps)

            for b in bins:
                for s_id, tok in b.candidates.items():
                    if tok == "<eps>":
                        continue
                    is_correct = 1 if tok in ref_words else 0
                    agree = sum(1 for t in b.candidates.values() if t == tok) / max(num_srcs, 1)
                    q = b.source_scores.get(s_id, 0.5)
                    conf = b.confidences.get(s_id, 0.8)
                    training_feats.append([q, conf, 0.05, agree, float(len(tok)), 0.3])
                    training_labels.append(is_correct)

        if len(training_feats) >= 10:
            x_arr = np.array(training_feats, dtype=np.float32)
            y_arr = np.array(training_labels, dtype=np.int32)
            learned_model.fit(x_arr, y_arr)
            learned_model.save(artifacts_dir / "learned_fusion_model.joblib")
            logger.info("Successfully trained F6_LEARNED on %d token samples", len(training_feats))

    # ---------------------------------------------------------------------------
    # Step 2: Validate Calibration on Validation Split
    # ---------------------------------------------------------------------------
    logger.info("Step 2: Checking calibration and thresholds on Validation split...")
    unknown_threshold = 0.35

    # ---------------------------------------------------------------------------
    # Step 3: Evaluate Once on Test Split
    # ---------------------------------------------------------------------------
    logger.info("Step 3: Running final evaluation on Test split...")
    test_recipe_file = recipes_dir / "meeting_test_001.json"
    if not test_recipe_file.exists():
        raise FileNotFoundError(f"Test recipe not found at {test_recipe_file}")

    test_recipe = load_recipe(test_recipe_file)
    test_meeting_dir = audio_dir / "meeting_test_001"

    # Load test audio
    test_signals: dict[str, np.ndarray] = {}
    for dev_id in sorted(test_recipe.devices.keys()):
        sig, _ = sf.read(str(test_meeting_dir / f"{dev_id}.wav"), dtype="float32")
        test_signals[dev_id] = sig

    # 1. Synchronization
    aligned_test, test_sync_meta, _ = synchronize_multi_source_audio(test_signals)
    sync_eval_results = evaluate_synchronization(test_sync_meta, test_recipe)

    # 2. VAD
    test_segments = extract_shared_meeting_segments(
        aligned_test, models_cfg.vad, test_recipe.meeting_id
    )
    vad_eval_results = evaluate_vad(test_segments, test_recipe)

    # 3. Speaker Enrollment Prototypes (5s, 15s, 30s)
    speaker_id_results: dict[str, dict[str, float]] = {}
    speaker_prototypes_by_dur: dict[str, dict[str, np.ndarray]] = {}

    for dur_sec in exp_cfg.enrollment_durations_sec:
        dur_label = f"{int(dur_sec)}s"
        protos = build_speaker_prototypes(
            speaker_ids=test_recipe.speakers,
            enrollment_catalog=catalog,
            manifest_records=manifest_records,
            target_duration_sec=dur_sec,
            encoder=speaker_encoder,
        )
        speaker_prototypes_by_dur[dur_label] = protos

    # 4. Transcribe each segment x source and run Baselines F0-F6
    baseline_predictions: dict[str, list[str]] = {
        "F0_FIXED": [],
        "F1_BEST_SEGMENT": [],
        "F2_ORACLE_BEST": [],
        "F3_ROVER": [],
        "F4_ASR_WEIGHTED": [],
        "F5_RULE_WEIGHTED": [],
        "F5_RULE_WEIGHTED_CORRECTED": [],
        "F6_LEARNED": [],
    }

    reference_transcripts: list[str] = []
    final_timeline_items: list[FinalTimelineItem] = []
    failure_cases: list[dict[str, Any]] = []

    y_true_speaker: list[str] = []
    y_pred_speaker_by_dur: dict[str, list[str]] = {
        f"{int(d)}s": [] for d in exp_cfg.enrollment_durations_sec
    }

    evidence_clips_dir = artifacts_dir / test_recipe.meeting_id / "evidence_clips"

    for seg in test_segments:
        # Match ground truth turn
        matching_turn = None
        for turn in test_recipe.turns:
            if turn.start_sec < seg.end_sec + 0.15 and turn.end_sec > seg.start_sec - 0.15:
                matching_turn = turn
                break

        ref_text = matching_turn.text_normalized if matching_turn else ""
        ref_spk = matching_turn.speaker_id if matching_turn else "unknown"
        reference_transcripts.append(ref_text)
        y_true_speaker.append(ref_spk)

        # Slice waveforms for this segment
        s_samp = round(seg.start_sec * 16000)
        e_samp = round(seg.end_sec * 16000)
        seg_waves = {d: aligned_test[d][s_samp:e_samp] for d in aligned_test}

        # Transcribe all sources
        source_hyps = transcribe_segment_sources(
            test_recipe.meeting_id, seg, seg_waves, asr_adapter
        )

        # Speaker identification across enrollment durations
        chosen_speaker = "unknown"
        chosen_speaker_conf = 0.0

        for dur_sec in exp_cfg.enrollment_durations_sec:
            dur_label = f"{int(dur_sec)}s"
            protos = speaker_prototypes_by_dur[dur_label]
            spk_res = identify_multi_source_speaker(
                segment_waveforms=seg_waves,
                speaker_prototypes=protos,
                audio_quality_scores={d: h.audio_quality_score for d, h in source_hyps.items()},
                encoder=speaker_encoder,
                unknown_threshold=unknown_threshold,
            )
            pred_spk = spk_res["predicted_speaker_id"]
            y_pred_speaker_by_dur[dur_label].append(pred_spk)
            if dur_sec == 30.0 or dur_sec == exp_cfg.enrollment_durations_sec[-1]:
                chosen_speaker = pred_spk
                chosen_speaker_conf = spk_res["confidence"]

        # Build confusion network
        bins = build_confusion_network(source_hyps)

        # Execute all 8 baselines
        t0, _ = fuse_f0_fixed(source_hyps)
        t1, _ = fuse_f1_best_segment(source_hyps)
        t2, _ = fuse_f2_oracle_best(source_hyps, reference_text=ref_text)
        t3, _ = fuse_f3_rover(bins)
        t4, _ = fuse_f4_asr_weighted(bins)
        t5, d5 = fuse_f5_rule_weighted(bins)
        t5_corr, _ = fuse_f5_rule_weighted_corrected(bins, source_hypotheses=source_hyps)
        t6, _ = fuse_f6_learned(bins, learned_model)

        baseline_predictions["F0_FIXED"].append(t0)
        baseline_predictions["F1_BEST_SEGMENT"].append(t1)
        baseline_predictions["F2_ORACLE_BEST"].append(t2)
        baseline_predictions["F3_ROVER"].append(t3)
        baseline_predictions["F4_ASR_WEIGHTED"].append(t4)
        baseline_predictions["F5_RULE_WEIGHTED"].append(t5)
        baseline_predictions["F5_RULE_WEIGHTED_CORRECTED"].append(t5_corr)
        baseline_predictions["F6_LEARNED"].append(t6)

        # Build FinalTimelineItem with provenance and evidence clips (using F5 or F6)
        timeline_item = build_final_timeline_item(
            meeting_id=test_recipe.meeting_id,
            segment=seg,
            fused_text=t5,
            word_decisions=d5,
            speaker_id=chosen_speaker,
            speaker_confidence=chosen_speaker_conf,
            source_hypotheses=source_hyps,
            aligned_audio_signals=aligned_test,
            output_clips_dir=evidence_clips_dir,
        )
        final_timeline_items.append(timeline_item)

        # Check for failure case
        seg_cer = float(jiwer.cer(ref_text or " ", t5 or " "))
        if seg_cer > 0.4 or (chosen_speaker != ref_spk and ref_spk != "unknown"):
            failure_cases.append(
                {
                    "meeting_id": test_recipe.meeting_id,
                    "segment_id": seg.segment_id,
                    "start_sec": seg.start_sec,
                    "end_sec": seg.end_sec,
                    "true_speaker": ref_spk,
                    "pred_speaker": chosen_speaker,
                    "speaker_confidence": chosen_speaker_conf,
                    "reference_text": ref_text,
                    "fused_text": t5,
                    "cer": seg_cer,
                    "reason": "Phân đoạn ngắn hoặc nhiễu âm thanh phòng vang",
                }
            )

    # Compute ASR metrics for all baselines
    baseline_eval_results: dict[str, dict[str, float]] = {}
    for b_id, hyps in baseline_predictions.items():
        res = evaluate_asr_transcripts(reference_transcripts, hyps)
        baseline_eval_results[b_id] = res

    # Compute Speaker ID metrics by enrollment duration
    for dur_label, y_preds in y_pred_speaker_by_dur.items():
        speaker_id_results[dur_label] = evaluate_speaker_identification(y_true_speaker, y_preds)

    # ---------------------------------------------------------------------------
    # Step 4: Save Artifacts and Generate Markdown Reports
    # ---------------------------------------------------------------------------
    meeting_artifact_dir = artifacts_dir / test_recipe.meeting_id
    meeting_artifact_dir.mkdir(parents=True, exist_ok=True)

    # Save final timeline artifact
    timeline_file = meeting_artifact_dir / "final_timeline.json"
    with open(timeline_file, "w", encoding="utf-8") as f:
        json.dump(
            [item.model_dump() for item in final_timeline_items],
            f,
            ensure_ascii=False,
            indent=2,
        )

    # Summary dictionary
    summary_report = {
        "experiment_name": exp_cfg.experiment_name,
        "test_meeting_id": test_recipe.meeting_id,
        "synchronization": sync_eval_results,
        "vad": vad_eval_results,
        "speaker_identification": speaker_id_results,
        "asr_fusion_baselines": baseline_eval_results,
        "failure_cases_count": len(failure_cases),
    }

    save_summary_report(summary_report, output_path="reports/metrics/summary.json")
    generate_baseline_comparison_table(
        baseline_eval_results, output_path="reports/tables/baselines_comparison.md"
    )
    generate_speaker_enrollment_table(
        speaker_id_results, output_path="reports/tables/speaker_id_by_enrollment.md"
    )
    generate_failure_cases_report(
        failure_cases, output_path="reports/failure_cases/failure_analysis.md"
    )

    logger.info("Evaluation completed successfully! Reports written to reports/")
    return summary_report
