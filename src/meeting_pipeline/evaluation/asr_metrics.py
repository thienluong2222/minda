"""ASR CER and WER evaluation metrics.

Specification: Section 11.3 of docs/PLAN_VIVOS_SYNTHETIC_PIPELINE.md.
"""

from __future__ import annotations

from typing import Any

import jiwer


def evaluate_asr_transcripts(
    references: list[str],
    hypotheses: list[str],
) -> dict[str, Any]:
    """Compute CER (primary) and WER (secondary) along with S/D/I components."""
    if not references or not hypotheses:
        return {
            "cer": 0.0,
            "wer": 0.0,
            "substitutions": 0,
            "deletions": 0,
            "insertions": 0,
            "hits": 0,
            "total_samples": 0,
        }

    # Clean references and hypotheses: replace empty strings with placeholder if needed
    clean_refs = [r if r.strip() else "" for r in references]
    clean_hyps = [h if h.strip() else "" for h in hypotheses]

    # Character Error Rate (CER)
    cer = float(jiwer.cer(clean_refs, clean_hyps))

    # Word Error Rate (WER)
    wer_output = jiwer.process_words(clean_refs, clean_hyps)
    wer = float(wer_output.wer)

    return {
        "cer": round(cer, 4),
        "wer": round(wer, 4),
        "substitutions": wer_output.substitutions,
        "deletions": wer_output.deletions,
        "insertions": wer_output.insertions,
        "hits": wer_output.hits,
        "total_samples": len(references),
    }
