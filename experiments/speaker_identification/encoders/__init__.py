"""Encoders package for speaker identification."""

from __future__ import annotations

from experiments.speaker_identification.encoders.base import BaseSpeakerEncoder
from experiments.speaker_identification.encoders.mfcc import MFCCEncoder
from experiments.speaker_identification.encoders.pyannote_wespeaker import PyannoteWeSpeakerEncoder
from experiments.speaker_identification.encoders.speechbrain_ecapa import SpeechBrainECAPAEncoder
from experiments.speaker_identification.encoders.speechbrain_xvector import (
    SpeechBrainXVectorEncoder,
)
from experiments.speaker_identification.encoders.transformers_wavlm import TransformersWavLMEncoder

__all__ = [
    "BaseSpeakerEncoder",
    "MFCCEncoder",
    "PyannoteWeSpeakerEncoder",
    "SpeechBrainECAPAEncoder",
    "SpeechBrainXVectorEncoder",
    "TransformersWavLMEncoder",
]
