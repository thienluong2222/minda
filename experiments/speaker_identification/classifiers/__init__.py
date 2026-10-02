"""Classifiers package for speaker identification."""

from __future__ import annotations

from experiments.speaker_identification.classifiers.base import BaseClassifier
from experiments.speaker_identification.classifiers.cosine_knn import CosineKNNClassifier
from experiments.speaker_identification.classifiers.cosine_prototype import (
    CosinePrototypeClassifier,
)
from experiments.speaker_identification.classifiers.linear_svm import LinearSVMClassifier

__all__ = [
    "BaseClassifier",
    "CosineKNNClassifier",
    "CosinePrototypeClassifier",
    "LinearSVMClassifier",
]
