"""Confusion network builder across multiple synchronized ASR hypotheses.

Specification: Section 13.2 of docs/PLAN_VIVOS_SYNTHETIC_PIPELINE.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from meeting_pipeline.domain.contracts import SourceHypothesis
from meeting_pipeline.fusion.alignment import EPSILON_TOKEN, align_word_sequences


@dataclass
class ConfusionBin:
    """A single alignment slot containing candidate tokens from all sources."""

    bin_idx: int
    candidates: dict[str, str] = field(default_factory=dict)
    confidences: dict[str, float] = field(default_factory=dict)
    source_scores: dict[str, float] = field(default_factory=dict)


def build_confusion_network(
    source_hypotheses: dict[str, SourceHypothesis],
    backbone_source_id: str | None = None,
) -> list[ConfusionBin]:
    """Build a multi-source confusion network aligned to a backbone hypothesis."""
    source_hypotheses = {
        source_id: hypothesis
        for source_id, hypothesis in source_hypotheses.items()
        if hypothesis.asr_status == "transcribed" and hypothesis.text.strip()
    }
    if not source_hypotheses:
        return []

    # Pick backbone: source with highest transcript_quality_score or longest text
    if backbone_source_id and backbone_source_id in source_hypotheses:
        bb_id = backbone_source_id
    else:
        bb_id = max(
            source_hypotheses.keys(),
            key=lambda k: (
                source_hypotheses[k].transcript_quality_score,
                len(source_hypotheses[k].text.split()),
            ),
        )

    bb_hyp = source_hypotheses[bb_id]
    bb_tokens = [w for w in bb_hyp.text.split() if w.strip()]

    # If all sources are empty
    if not bb_tokens:
        # Check if any other source has tokens
        other_with_tokens = [k for k, h in source_hypotheses.items() if h.text.strip()]
        if not other_with_tokens:
            return []
        bb_id = max(other_with_tokens, key=lambda k: len(source_hypotheses[k].text.split()))
        bb_hyp = source_hypotheses[bb_id]
        bb_tokens = [w for w in bb_hyp.text.split() if w.strip()]

    # Word confidence lookup helper
    def get_word_conf(hyp: SourceHypothesis, token: str, idx: int) -> float:
        if hyp.words and idx < len(hyp.words):
            word_confidence = hyp.words[idx].asr_confidence
            if word_confidence is not None:
                return word_confidence
        mean_confidence = hyp.asr_features.get("mean_confidence")
        # Neutral internal voting weight when the model does not expose a probability.
        return float(mean_confidence) if mean_confidence is not None else 0.5

    # Initialize bins with backbone tokens
    bins: list[ConfusionBin] = []
    for idx, token in enumerate(bb_tokens):
        c_bin = ConfusionBin(bin_idx=idx)
        c_bin.candidates[bb_id] = token
        c_bin.confidences[bb_id] = get_word_conf(bb_hyp, token, idx)
        c_bin.source_scores[bb_id] = bb_hyp.transcript_quality_score
        bins.append(c_bin)

    # Align every other source against the backbone
    other_sources = [s for s in sorted(source_hypotheses.keys()) if s != bb_id]

    for src_id in other_sources:
        hyp = source_hypotheses[src_id]
        tokens = [w for w in hyp.text.split() if w.strip()]

        bb_aligned, src_aligned = align_word_sequences(bb_tokens, tokens)

        # Merge src_aligned into bins
        bb_ptr = 0
        src_token_idx = 0

        for a_idx, bb_tok in enumerate(bb_aligned):
            src_tok = src_aligned[a_idx]
            src_conf = (
                get_word_conf(hyp, src_tok, src_token_idx) if src_tok != EPSILON_TOKEN else 0.0
            )
            if src_tok != EPSILON_TOKEN:
                src_token_idx += 1

            if bb_tok != EPSILON_TOKEN:
                # Matches an existing bin
                if bb_ptr < len(bins):
                    bins[bb_ptr].candidates[src_id] = src_tok
                    bins[bb_ptr].confidences[src_id] = src_conf
                    bins[bb_ptr].source_scores[src_id] = hyp.transcript_quality_score
                bb_ptr += 1
            else:
                # Insertion in source not present in backbone
                # Insert a new bin before current bb_ptr
                new_bin = ConfusionBin(bin_idx=len(bins))
                new_bin.candidates[bb_id] = EPSILON_TOKEN
                new_bin.confidences[bb_id] = 0.0
                new_bin.source_scores[bb_id] = bb_hyp.transcript_quality_score

                # Set empty for other already aligned sources
                for prev_src in other_sources:
                    if prev_src == src_id:
                        break
                    new_bin.candidates[prev_src] = EPSILON_TOKEN
                    new_bin.confidences[prev_src] = 0.0
                    new_bin.source_scores[prev_src] = source_hypotheses[
                        prev_src
                    ].transcript_quality_score

                new_bin.candidates[src_id] = src_tok
                new_bin.confidences[src_id] = src_conf
                new_bin.source_scores[src_id] = hyp.transcript_quality_score

                bins.insert(bb_ptr, new_bin)
                bb_ptr += 1

    # Ensure all bins have entries for all sources
    all_source_ids = sorted(source_hypotheses.keys())
    for b in bins:
        for s_id in all_source_ids:
            if s_id not in b.candidates:
                b.candidates[s_id] = EPSILON_TOKEN
                b.confidences[s_id] = 0.0
                b.source_scores[s_id] = source_hypotheses[s_id].transcript_quality_score

    return bins
