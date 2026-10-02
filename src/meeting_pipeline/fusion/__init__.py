"""Transcript fusion, alignment, confusion network and provenance package."""

from meeting_pipeline.fusion.alignment import EPSILON_TOKEN, align_word_sequences
from meeting_pipeline.fusion.baselines import (
    fuse_f0_fixed,
    fuse_f1_best_segment,
    fuse_f2_oracle_best,
    fuse_f3_rover,
    fuse_f4_asr_weighted,
    fuse_f5_rule_weighted,
    fuse_f6_learned,
)
from meeting_pipeline.fusion.confusion_network import ConfusionBin, build_confusion_network
from meeting_pipeline.fusion.features import (
    compute_audio_quality_score,
    compute_transcript_quality_score,
    extract_acoustic_features,
)
from meeting_pipeline.fusion.model import LearnedFusionModel
from meeting_pipeline.fusion.provenance import build_final_timeline_item

__all__ = [
    "EPSILON_TOKEN",
    "ConfusionBin",
    "LearnedFusionModel",
    "align_word_sequences",
    "build_confusion_network",
    "build_final_timeline_item",
    "compute_audio_quality_score",
    "compute_transcript_quality_score",
    "extract_acoustic_features",
    "fuse_f0_fixed",
    "fuse_f1_best_segment",
    "fuse_f2_oracle_best",
    "fuse_f3_rover",
    "fuse_f4_asr_weighted",
    "fuse_f5_rule_weighted",
    "fuse_f6_learned",
]
