"""Attribute ASR errors to raw decoding, retry, and published timestamp anomalies."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.comparative_benchmark.common import OUT, setup, write_csv, write_json


def analyze():
    import jiwer

    from meeting_pipeline.data.vivos import normalize_vietnamese_text

    summaries = []
    examples = []
    for file in (OUT / "asr_mps_float16").glob("*/synthetic_test_predictions.jsonl"):
        final_errors = first_errors = words = retries = zero_duration = 0
        added = removed = 0
        per_sample = []
        for row in map(json.loads, file.read_text().splitlines()):
            if row["condition"] not in ("easy", "moderate", "stress"):
                continue
            result = row["result"]
            raw = result.get("raw_candidates", [])
            first_text = raw[0]["text"] if raw else result["text"]
            reference = normalize_vietnamese_text(row["reference"])
            final = jiwer.process_words(reference, normalize_vietnamese_text(result["text"]))
            first = jiwer.process_words(reference, normalize_vietnamese_text(first_text))
            fe = final.substitutions + final.deletions + final.insertions
            re = first.substitutions + first.deletions + first.insertions
            final_errors += fe
            first_errors += re
            words += final.hits + final.substitutions + final.deletions
            retries += len(raw) > 1
            added += max(0, fe - re)
            removed += max(0, re - fe)
            zero = sum(w["end_sec"] <= w["start_sec"] for w in result.get("words", []))
            zero_duration += zero
            per_sample.append(
                {
                    "model": file.parent.name,
                    "id": row["id"],
                    "condition": row["condition"],
                    "reference": reference,
                    "published_text": result["text"],
                    "first_raw_text": first_text,
                    "reference_words": final.hits + final.substitutions + final.deletions,
                    "published_errors": fe,
                    "first_decode_errors": re,
                    "net_errors_added": fe - re,
                    "published_zero_duration_words": zero,
                    "retry_attempts": max(0, len(raw) - 1),
                    "status": result["status"],
                }
            )
        summaries.append(
            {
                "model": file.parent.name,
                "condition": "simulated_only",
                "reference_words": words,
                "published_wer": final_errors / words,
                "first_decode_wer": first_errors / words,
                "gross_errors_added_after_first_decode": added,
                "gross_errors_removed_after_first_decode": removed,
                "net_wer_added_after_first_decode": (final_errors - first_errors) / words,
                "published_zero_duration_words": zero_duration,
                "retried_samples": retries,
                "worst_sample_error_share": max(r["published_errors"] for r in per_sample)
                / max(final_errors, 1),
                "scope": "diagnostic_only_no_test_based_decoder_changes_or_cherry_picked_exclusions",
                "raw_decode_caution": "A lower raw WER does not establish valid timestamps or make an unaccepted decode safe to publish.",
            }
        )
        examples.extend(sorted(per_sample, key=lambda x: x["published_errors"], reverse=True)[:5])
    write_json(OUT / "ASR_error_analysis.json", {"summary": summaries, "largest_errors": examples})
    write_csv(OUT / "ASR_error_analysis.csv", summaries)
    write_csv(OUT / "ASR_error_examples.csv", examples)
    return summaries


if __name__ == "__main__":
    setup()
    for result in analyze():
        print(result)
