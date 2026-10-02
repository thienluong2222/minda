"""Unit tests for MFCC feature extraction and KNN speaker classification."""

from __future__ import annotations

import numpy as np

from meeting_pipeline.application.speakers import SpeakerProfileInput
from meeting_pipeline.domain.speaker_classifier import (
    MFCCKNNSpeakerClassifier,
    extract_mfcc_feature_vector,
)


def _make_tone(freq: float, duration_sec: float = 2.0, sr: int = 16000) -> np.ndarray:
    """Generate harmonic test tone for acoustic distinctiveness."""
    t = np.linspace(0, duration_sec, int(sr * duration_sec), endpoint=False, dtype=np.float32)
    tone = np.sin(2 * np.pi * freq * t) + 0.5 * np.sin(2 * np.pi * (2 * freq) * t)
    return tone.astype(np.float32)


def test_mfcc_feature_extraction_shape_and_norm() -> None:
    sr = 16000
    wave = _make_tone(440.0, duration_sec=1.5, sr=sr)
    feat = extract_mfcc_feature_vector(wave, sr=sr, n_mfcc=20)

    # 20 MFCC + 20 Delta + 20 Delta2 = 60 * 2 (mean + std) = 120
    assert feat.shape == (120,)
    assert np.isclose(np.linalg.norm(feat), 1.0, atol=1e-5)


def test_mfcc_feature_extraction_short_audio() -> None:
    """Audio shorter than hop length should be safely padded without error."""
    sr = 16000
    wave = np.ones(50, dtype=np.float32)
    feat = extract_mfcc_feature_vector(wave, sr=sr)
    assert feat.shape == (120,)
    assert np.isclose(np.linalg.norm(feat), 1.0, atol=1e-5)


def test_mfcc_knn_speaker_identification() -> None:
    sr = 16000
    alice_sample = _make_tone(350.0, duration_sec=3.0, sr=sr)
    bob_sample = _make_tone(1400.0, duration_sec=3.0, sr=sr)

    alice_profile = SpeakerProfileInput(
        speaker_id="speaker-alice",
        display_name="Alice",
        embedding=np.zeros(192, dtype=np.float32),
        sample_waveforms=(alice_sample,),
    )
    bob_profile = SpeakerProfileInput(
        speaker_id="speaker-bob",
        display_name="Bob",
        embedding=np.zeros(192, dtype=np.float32),
        sample_waveforms=(bob_sample,),
    )

    clf = MFCCKNNSpeakerClassifier(
        profiles=[alice_profile, bob_profile],
        n_neighbors=3,
        metric="cosine",
        identity_threshold=0.25,
        identity_margin=0.05,
    )

    # Test clip matching Alice
    alice_test = _make_tone(350.0, duration_sec=1.2, sr=sr)
    pred_alice = clf.assign_speaker(alice_test, excluded=set())
    assert pred_alice["speaker_status"] == "identified"
    assert pred_alice["speaker_label"] == "Alice"
    assert pred_alice["profile_id"] == "speaker-alice"
    assert "knn_identified" in str(pred_alice["identity_decision_reason"])
    assert float(pred_alice["speaker_match_score"]) >= 0.25

    # Test clip matching Bob
    bob_test = _make_tone(1400.0, duration_sec=1.2, sr=sr)
    pred_bob = clf.assign_speaker(bob_test, excluded=set())
    assert pred_bob["speaker_status"] == "identified"
    assert pred_bob["speaker_label"] == "Bob"
    assert pred_bob["profile_id"] == "speaker-bob"
    assert "knn_identified" in str(pred_bob["identity_decision_reason"])


def test_mfcc_knn_unknown_fallback() -> None:
    """When a speech sample does not match any profile closely, fallback to anonymous cluster."""
    sr = 16000
    alice_sample = _make_tone(300.0, duration_sec=2.0, sr=sr)
    alice_profile = SpeakerProfileInput(
        speaker_id="speaker-alice",
        display_name="Alice",
        embedding=np.zeros(192, dtype=np.float32),
        sample_waveforms=(alice_sample,),
    )

    # Use strict identity threshold
    clf = MFCCKNNSpeakerClassifier(
        profiles=[alice_profile],
        n_neighbors=3,
        identity_threshold=0.99,  # Very high threshold so noise is rejected
        identity_margin=0.05,
    )

    # Test noise that won't pass 0.99 similarity
    noise_test = np.random.randn(sr * 2).astype(np.float32)
    pred_unknown = clf.assign_speaker(noise_test, excluded=set())
    assert pred_unknown["speaker_status"] == "unknown"
    assert pred_unknown["profile_id"] is None
    assert pred_unknown["speaker_label"] == "Speaker 1"
    assert "new_cluster" in str(pred_unknown["identity_decision_reason"])
