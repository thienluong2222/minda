"""Unit tests for speaker identification and ASR feature scoring (Milestone 5)."""

import numpy as np

from meeting_pipeline.adapters.phowhisper_asr import AsrResult, BaseAsrAdapter
from meeting_pipeline.asr.segment_asr import transcribe_segment_sources
from meeting_pipeline.domain.contracts import MeetingSegment
from meeting_pipeline.domain.transcription import TimedWord
from meeting_pipeline.evaluation.asr_metrics import evaluate_asr_transcripts
from meeting_pipeline.evaluation.speaker_metrics import evaluate_speaker_identification
from meeting_pipeline.fusion.features import (
    compute_audio_quality_score,
    compute_transcript_quality_score,
    extract_acoustic_features,
)
from meeting_pipeline.speaker.identification import identify_multi_source_speaker


class DummyAsrAdapter(BaseAsrAdapter):
    """Mock ASR adapter for deterministic unit tests."""

    def transcribe(self, waveform: np.ndarray, sample_rate: int = 16000) -> AsrResult:
        if len(waveform) == 0:
            return AsrResult(text="", words=[], status="empty")
        return AsrResult(
            text="xin chào các bạn",
            words=[
                TimedWord(text="xin", start_sec=0.1, end_sec=0.3, confidence=0.92),
                TimedWord(text="chào", start_sec=0.3, end_sec=0.5, confidence=0.88),
                TimedWord(text="các", start_sec=0.5, end_sec=0.7, confidence=0.85),
                TimedWord(text="bạn", start_sec=0.7, end_sec=0.9, confidence=0.90),
            ],
            status="transcribed",
        )


def test_acoustic_feature_extraction_and_scoring() -> None:
    wave = np.sin(2 * np.pi * 440 * np.linspace(0, 1, 16000)).astype(np.float32) * 0.5
    feats = extract_acoustic_features(wave, sample_rate=16000)

    assert "rms" in feats
    assert "snr_est" in feats
    assert "clipping_ratio" in feats
    assert "dropout_ratio" in feats
    assert feats["clipping_ratio"] == 0.0

    audio_q = compute_audio_quality_score(feats)
    assert 0.0 <= audio_q <= 1.0

    transcript_q = compute_transcript_quality_score(audio_q, asr_confidence=0.9)
    assert 0.0 <= transcript_q <= 1.0


def test_identify_multi_source_speaker() -> None:
    # 2 enrolled speakers with orthogonal prototypes
    proto_spk1 = np.zeros(192, dtype=np.float32)
    proto_spk1[0] = 1.0
    proto_spk2 = np.zeros(192, dtype=np.float32)
    proto_spk2[1] = 1.0

    prototypes = {"spk_01": proto_spk1, "spk_02": proto_spk2}

    # Dummy class mock for encoder
    class MockEncoder:
        def encode(self, wave: np.ndarray) -> np.ndarray:
            # If wave amplitude is high, return spk_01 embedding, else spk_02
            emb = np.zeros(192, dtype=np.float32)
            if np.mean(wave) > 0.5:
                emb[0] = 1.0
            else:
                emb[1] = 1.0
            return emb

    mock_enc = MockEncoder()
    wave_dev1 = np.ones(3200, dtype=np.float32) * 0.8  # near spk_01
    wave_dev2 = np.ones(3200, dtype=np.float32) * 0.2  # near spk_02

    waveforms = {"dev_01": wave_dev1, "dev_02": wave_dev2}
    qualities = {"dev_01": 0.9, "dev_02": 0.3}

    res = identify_multi_source_speaker(
        segment_waveforms=waveforms,
        speaker_prototypes=prototypes,
        audio_quality_scores=qualities,
        encoder=mock_enc,  # type: ignore[arg-type]
        fixed_source_id="dev_01",
        temperature=2.0,
    )

    assert res["predicted_speaker_id"] == "spk_01"
    assert "baseline_predictions" in res
    assert res["baseline_predictions"]["fixed_source"] == "spk_01"


def test_transcribe_segment_sources() -> None:
    seg = MeetingSegment(
        schema_version="1.0",
        meeting_id="m1",
        segment_id="seg_0001",
        start_sec=1.0,
        end_sec=2.5,
    )
    waves = {
        "dev_01": np.ones(24000, dtype=np.float32) * 0.3,
        "dev_02": np.ones(24000, dtype=np.float32) * 0.1,
    }
    dummy_asr = DummyAsrAdapter()

    hyps = transcribe_segment_sources(
        meeting_id="m1",
        segment=seg,
        segment_waveforms=waves,
        asr_adapter=dummy_asr,
    )

    assert "dev_01" in hyps
    assert "dev_02" in hyps
    assert hyps["dev_01"].text == "xin chào các bạn"
    assert len(hyps["dev_01"].words) == 4
    assert 0.0 <= hyps["dev_01"].transcript_quality_score <= 1.0


def test_speaker_and_asr_evaluation_metrics() -> None:
    # Speaker eval
    y_true = ["spk1", "spk1", "spk2", "spk3"]
    y_pred = ["spk1", "spk2", "spk2", "spk3"]
    spk_res = evaluate_speaker_identification(y_true, y_pred)
    assert spk_res["accuracy"] == 0.75
    assert spk_res["macro_f1"] > 0.6

    # ASR eval
    refs = ["tôi muốn đi học"]
    hyps = ["tôi muốn đi làm"]
    asr_res = evaluate_asr_transcripts(refs, hyps)
    assert asr_res["wer"] == 0.25  # 1 substitution out of 4 words
    assert asr_res["cer"] > 0.0
