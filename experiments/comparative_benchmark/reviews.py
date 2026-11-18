"""Evidence-based adaptation screening, explicitly limited to simulated conditions."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.comparative_benchmark.common import OUT, read_json, write_csv, write_json


def refresh():
    reviews = []
    error_path = OUT / "ASR_error_analysis.json"
    error_analysis = (
        {r["model"]: r for r in read_json(error_path)["summary"]} if error_path.exists() else {}
    )
    group = (
        "asr_mps_float16"
        if (OUT / "asr_mps_float16").exists()
        else "asr_mps"
        if (OUT / "asr_mps").exists()
        else "asr"
    )
    for folder in sorted((OUT / group).glob("*")):
        path = folder / "synthetic_test_summary.json"
        if not path.exists():
            continue
        rows = read_json(path)
        clean = next((r for r in rows if r["condition"] == "clean_control"), None)
        simulated = [r for r in rows if r["condition"] in ("easy", "moderate", "stress")]
        if not clean or not simulated:
            continue
        noisy = sum(r["wer"] * r["reference_words"] for r in simulated) / sum(
            r["reference_words"] for r in simulated
        )
        all_row = next(r for r in rows if r["condition"] == "all")
        detail = error_analysis.get(folder.name, {})
        if (
            all_row["wer"] - all_row["first_decode_wer"] > 0.05
            or detail.get("net_wer_added_after_first_decode", 0) > 0.03
            or detail.get("published_zero_duration_words", 0) >= 3
        ):
            action = "adapter_or_timestamp_guard_first"
            explanation = "Raw/published comparisons or zero-duration word timestamps expose decoding, retry, or guard problems; inspect these before training weights."
        elif noisy - clean["wer"] > 0.10:
            action = "acoustic_domain_finetuning_candidate"
            explanation = "Acoustic degradation persists with fixed decoding; compare a stronger pretrained model and matched-noise adaptation before deciding to train."
        elif clean["wer"] > 0.20:
            action = "inspect_transcript_and_decoding_before_finetuning"
            explanation = "Clean-control errors are substantial; inspect alignment, normalization, speech coverage, and replacements before attributing them to model capacity."
        else:
            action = "no_finetuning_priority_from_this_screen"
            explanation = (
                "This simulated sample does not provide a strong reason to prioritize fine-tuning."
            )
        reviews.append(
            {
                "task": "ASR",
                "model": folder.name,
                "clean_wer": clean["wer"],
                "simulated_wer": noisy,
                "published_wer": all_row["wer"],
                "first_decode_wer": all_row["first_decode_wer"],
                "simulated_first_decode_wer": detail.get("first_decode_wer"),
                "net_wer_added_after_first_decode": detail.get("net_wer_added_after_first_decode"),
                "published_zero_duration_words": detail.get("published_zero_duration_words"),
                "recommendation": action,
                "reason": explanation,
                "evidence": "paired_simulated_VIVOS_utterances",
                "certainty": "screening_only_not_a_real_meeting_training_verdict",
            }
        )
    for file in sorted((OUT / "speaker_synthetic").glob("E*_summary.json")):
        rows = [r for r in read_json(file) if r["k"] == 3 and r["classifier"] == "cosine_prototype"]
        easy = next((r for r in rows if r["dataset"] == "sim_easy_test"), None)
        stress = next((r for r in rows if r["dataset"] == "sim_stress_test"), None)
        if not easy or not stress:
            continue
        if easy["closed_set_accuracy"] > 0.90 and easy["unknown_rejection"] < 0.75:
            action = "open_set_calibration_first"
        elif easy["macro_f1"] - stress["macro_f1"] > 0.10:
            action = "noise_robustness_adaptation_candidate"
        elif easy["closed_set_accuracy"] < 0.80:
            action = "prefer_stronger_encoder_or_matched_domain_training"
        else:
            action = "no_finetuning_priority_from_this_screen"
        if file.stem.startswith("E0"):
            action = "traditional_feature_baseline_not_neural_finetuning"
        reviews.append(
            {
                "task": "speaker",
                "model": file.stem.replace("_summary", ""),
                "easy_macro_f1": easy["macro_f1"],
                "stress_macro_f1": stress["macro_f1"],
                "recommendation": action,
                "reason": "Compare closed-set identity accuracy, unknown rejection, and acoustic degradation after validation-only calibration.",
                "evidence": "simulated_queries_clean_enrollment",
                "certainty": "screening_only_not_a_real_meeting_training_verdict",
            }
        )
    for file in sorted((OUT / "segmentation").glob("*/summary.json")):
        for row in [r for r in read_json(file) if r["condition"] == "all"]:
            overlap = row["task"] == "overlap"
            reviews.append(
                {
                    "task": row["task"],
                    "model": row["model"],
                    "f1": row["f1"],
                    "recommendation": "verify_activity_reference_and_endpointing_before_finetuning"
                    if overlap
                    else "no_finetuning_priority_from_this_screen"
                    if row["f1"] >= 0.9
                    else "calibration_or_domain_adaptation_candidate",
                    "reason": "Overlap uses utterance-extent proxy labels; consult the dry-source activity sensitivity diagnostic before attributing misses to model weights."
                    if overlap
                    else "Speech detection is already strong on these simulated conditions; boundary/merge/padding calibration is cheaper than retraining.",
                    "evidence": "simulated_meeting_source_1_with_reserved_VIVOS_speakers",
                    "certainty": "synthetic_activity_reference_only",
                }
            )
    for file in sorted((OUT / "ocr").glob("*/summary.json")):
        rows = read_json(file)
        clean = next(r for r in rows if r["condition"] == "clean")
        stress = next(r for r in rows if r["condition"] == "stress")
        audit_path = file.parent / "charset_audit.json"
        eligible = not audit_path.exists() or read_json(audit_path).get(
            "eligible_for_full_Vietnamese_orthography", True
        )
        reviews.append(
            {
                "task": "OCR",
                "model": file.parent.name,
                "clean_cer": clean["cer"],
                "stress_cer": stress["cer"],
                "eligible_for_full_Vietnamese_orthography": eligible,
                "recommendation": "select_checkpoint_with_complete_Vietnamese_alphabet_first"
                if not eligible
                else "font_noise_adaptation_candidate"
                if stress["cer"] - clean["cer"] > 0.10
                else "no_finetuning_priority_from_this_screen",
                "reason": "This checkpoint cannot emit required Vietnamese letters or their combining marks. Ordinary fine-tuning with its existing output alphabet cannot solve that limitation."
                if not eligible
                else "Recognition-only comparison on identical rendered crops. Check page detection, scan quality, and reading order separately before training.",
                "evidence": "rendered_Vietnamese_text_known_by_construction",
                "certainty": "not_real_scans_or_handwriting",
            }
        )
    for file in sorted((OUT / "text").glob("*/summary.json")):
        rows = [r for r in read_json(file) if r["split"] == "test"]
        for row in rows:
            action = (
                "clustering_selection_or_thresholds_first"
                if row["ari"] < 0.5 and row["oracle_k4_ari_diagnostic"] > 0.7
                else "no_finetuning_priority_from_this_screen"
                if row["ari"] > 0.7
                else "inspect_semantic_examples_before_embedding_finetuning"
            )
            reviews.append(
                {
                    "task": "topic_clustering",
                    "model": row["encoder"] + "+" + row["clusterer"],
                    "ari": row["ari"],
                    "collapse_rate": row["collapse_rate"],
                    "oracle_k4_ari_diagnostic": row["oracle_k4_ari_diagnostic"],
                    "recommendation": action,
                    "reason": "Separate semantic representation quality from automatic cluster-count selection; the templates are deliberately held out by split.",
                    "evidence": "scripted_meeting_topics_with_construction_labels",
                    "certainty": "synthetic_semantic_screen_only",
                }
            )
    for file in sorted((OUT / "separation").glob("*/summary.json")):
        row = next(r for r in read_json(file) if r["condition"] == "all")
        reviews.append(
            {
                "task": "separation",
                "model": row["model"],
                "si_sdr_improvement_db": row["si_sdr_improvement_db"],
                "negative_improvement_rate": row["negative_improvement_rate"],
                "recommendation": "check_target_and_downstream_ASR_before_finetuning"
                if row["si_sdr_improvement_db"] < 0
                else "matched_acoustics_adaptation_candidate"
                if row["negative_improvement_rate"] > 0.25
                else "no_finetuning_priority_from_this_screen",
                "reason": "Targets are reverberant source images; some pretrained separators optimize dry-source reconstruction. This branch is currently skipped by the application.",
                "evidence": "simulated_two_speaker_Vietnamese_mixtures",
                "certainty": "no_claim_of_application_overlap_transcription_gain",
            }
        )
    fusion = OUT / "fusion/summary.json"
    if fusion.exists():
        reviews.append(
            {
                "task": "fusion",
                "model": "F6_LEARNED",
                "recommendation": "collect_matched_ASR_hypotheses_and_retrain_small_fusion_classifier",
                "reason": "The development-trained logistic classifier was tested on scripted transcript corruptions. Actual model confidences and error correlations must be represented before deploying its weights.",
                "evidence": "algorithm_execution_on_constructed_hypotheses",
                "certainty": "not_a_pretrained_ASR_quality_benchmark",
            }
        )
    clustering = OUT / "speaker_clustering/summary.json"
    if clustering.exists():
        rows = [r for r in read_json(clustering) if r["condition"] == "all"]
        for encoder in sorted({r["encoder"] for r in rows}):
            current = next(
                r for r in rows if r["encoder"] == encoder and r["method"] == "ahc_current"
            )
            calibrated = next(
                r for r in rows if r["encoder"] == encoder and r["method"] == "ahc_calibrated"
            )
            reviews.append(
                {
                    "task": "speaker_clustering",
                    "model": encoder + "+AHC",
                    "current_ari": current["ari"],
                    "calibrated_ari": calibrated["ari"],
                    "recommendation": "validation_calibration_before_encoder_finetuning",
                    "reason": "Threshold calibration can change clustering quality with the same frozen embeddings. Native pipeline replay must also include turn-detection errors.",
                    "evidence": "oracle_turn_synthetic_queries",
                    "certainty": "not_full_meeting_DER",
                }
            )
    retrieval = OUT / "retrieval/summary.json"
    if retrieval.exists():
        for row in read_json(retrieval):
            reviews.append(
                {
                    "task": "retrieval",
                    "model": row["method"],
                    "hit_at_2": row["hit_at_2"],
                    "recommendation": "make_relevance_benchmark_more_discriminative_before_training",
                    "reason": "All four methods reach perfect Hit@2 on these scripted topic queries. Add harder queries and fact-level relevance before claiming a winner or training embeddings.",
                    "evidence": "scripted_topic_relevance_proxy",
                    "certainty": "not_fact_entailment",
                }
            )
    write_json(OUT / "model_reviews.json", reviews)
    write_csv(OUT / "model_reviews.csv", reviews)
    return reviews


if __name__ == "__main__":
    for row in refresh():
        print(row["task"], row["model"], row["recommendation"])
