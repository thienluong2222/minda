from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf

from meeting_pipeline.adapters.phowhisper_asr import AsrResult, FakeAsrAdapter
from meeting_pipeline.application.speakers import SpeakerProfileInput
from meeting_pipeline.config import load_config
from meeting_pipeline.domain.contracts import MeetingSegment, VadConfig
from meeting_pipeline.domain.transcription import TimedWord
from meeting_pipeline.pipeline.multi_source_fusion import MultiSourceFusionPipeline
from meeting_pipeline.pipeline.speaker_turns import SpeakerTurn


class _OneTurnDetector:
    def detect(self, aligned_paths, segments, reference_source, duration_sec):
        del aligned_paths, reference_source, duration_sec
        return [
            SpeakerTurn(
                turn_id="turn_0000",
                speech_region_id=segments[0].segment_id,
                start_sec=segments[0].start_sec,
                end_sec=segments[0].end_sec,
                track_id="local-1",
                speaker_count=1,
            )
        ]


class _FixedTurns:
    def __init__(self, overlap: bool) -> None:
        self.overlap = overlap

    def detect(self, aligned_paths, segments, reference_source, duration_sec):
        del aligned_paths, reference_source, duration_sec
        bounds = [(0.3, 1.7), (0.3, 1.7)] if self.overlap else [(0.1, 0.95), (0.95, 1.8)]
        return [
            SpeakerTurn(
                turn_id=f"turn_{index:04d}",
                speech_region_id=segments[0].segment_id,
                start_sec=start,
                end_sec=end,
                track_id=f"local-{index + 1}",
                speaker_count=2 if self.overlap else 1,
                overlap_group_id="overlap-1" if self.overlap else None,
                supporting_source_ids=["source-1", "source-2"],
            )
            for index, (start, end) in enumerate(bounds)
        ]


class _FakeSeparator:
    def __init__(self) -> None:
        self.calls = 0

    def separate(self, signal, start_sec, end_sec, context_sec):
        self.calls += 1
        del signal, context_sec
        sample_rate = 16000
        time = np.arange(round((end_sec - start_sec) * sample_rate)) / sample_rate
        return [
            (0.1 * np.sin(2 * np.pi * frequency * time)).astype(np.float32)
            for frequency in (220, 440)
        ]


def _one_segment(
    signals: dict[str, np.ndarray],
    _vad_config: VadConfig,
    meeting_id: str,
    _sample_rate: int,
) -> list[MeetingSegment]:
    assert len(signals) == 2
    return [
        MeetingSegment(
            meeting_id=meeting_id,
            segment_id="seg_0000",
            start_sec=0.1,
            end_sec=1.8,
        )
    ]


def _asr_result(text: str) -> AsrResult:
    tokens = text.split()
    return AsrResult(
        text=text,
        words=[
            TimedWord(
                text=token,
                start_sec=index * 0.25,
                end_sec=(index + 1) * 0.25,
                confidence=0.9,
            )
            for index, token in enumerate(tokens)
        ],
        status="transcribed",
    )


def test_multi_source_backend_fuses_all_sources_and_writes_provenance(tmp_path: Path) -> None:
    sample_rate = 16000
    time = np.arange(sample_rate * 2, dtype=np.float32) / sample_rate
    source_a = (0.18 * np.sin(2 * np.pi * 220 * time)).astype(np.float32)
    source_b = (0.14 * np.sin(2 * np.pi * 220 * time + 0.05)).astype(np.float32)
    source_paths = [tmp_path / "phone-a.wav", tmp_path / "phone-b.wav"]
    sf.write(source_paths[0], source_a, sample_rate)
    sf.write(source_paths[1], source_b, sample_rate)

    config = load_config(Path("configs/default.yaml"))
    config.paths.data_dir = tmp_path / "data"
    config.paths.model_cache_dir = tmp_path / "models"
    config.identity["method"] = "mfcc_knn"
    asr = FakeAsrAdapter(
        results=[
            _asr_result("xin chào bạn"),
            _asr_result("xin chào các bạn"),
        ]
    )

    run_dir = MultiSourceFusionPipeline(
        config,
        asr_adapter=asr,
        segment_extractor=_one_segment,
        turn_detector=_OneTurnDetector(),
    ).run("Demo fusion", source_paths, fusion_method="F5_RULE_WEIGHTED")

    timeline = json.loads((run_dir / "timeline.json").read_text(encoding="utf-8"))
    assert timeline["schema_version"] == "2.0"
    assert len(timeline["segments"]) == 1
    segment = timeline["segments"][0]
    assert segment["fusion_method"] == "F5_RULE_WEIGHTED"
    assert segment["text"]
    assert len(segment["source_evidence"]) == 2
    assert {item["candidate_scores"]["transcript"] for item in segment["source_evidence"]} == {
        "xin chào bạn",
        "xin chào các bạn",
    }
    assert segment["provenance"]["word_provenance"]
    assert any(
        len(word["supporting_sources"]) == 2 for word in segment["provenance"]["word_provenance"]
    )
    for relative_path in segment["original_clip_artifact_ids"]:
        assert (run_dir / relative_path).is_file()

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["backend"] == "multi_source_transcript_fusion"
    assert manifest["fusion_method_used"] == "F5_RULE_WEIGHTED"
    assert (run_dir / "source_hypotheses.json").is_file()
    assert (run_dir / "fusion_decisions.json").is_file()
    turns = json.loads((run_dir / "speaker_turns.json").read_text(encoding="utf-8"))
    assert len(turns["turns"]) == 1
    assert segment["speech_region_id"] == "seg_0000"
    assert segment["turn_id"] == "turn_0000"


def test_two_adjacent_speakers_inside_one_vad_region_remain_distinct(tmp_path: Path) -> None:
    sample_rate = 16000
    time = np.arange(sample_rate * 2, dtype=np.float32) / sample_rate
    voice_a = np.sin(2 * np.pi * 220 * time)
    voice_b = np.sin(2 * np.pi * 440 * time)
    mixture = (0.1 * np.where(time < 0.95, voice_a, voice_b)).astype(np.float32)
    paths = [tmp_path / "a.wav", tmp_path / "b.wav"]
    sf.write(paths[0], mixture, sample_rate)
    sf.write(paths[1], mixture * 0.8, sample_rate)
    config = load_config(Path("configs/default.yaml"))
    config.paths.data_dir = tmp_path / "data"
    config.identity["method"] = "mfcc_knn"
    asr = FakeAsrAdapter(results=[_asr_result("xin chào")] * 2 + [_asr_result("tạm biệt")] * 2)

    run_dir = MultiSourceFusionPipeline(
        config,
        asr_adapter=asr,
        segment_extractor=_one_segment,
        turn_detector=_FixedTurns(overlap=False),
    ).run("Adjacent speakers", paths)
    timeline = json.loads((run_dir / "timeline.json").read_text(encoding="utf-8"))["segments"]
    assert len(timeline) == 2
    assert [item["text"] for item in timeline] == ["xin chào", "tạm biệt"]
    assert len({item["track_id"] for item in timeline}) == 2
    assert len({item["speaker_label"] for item in timeline}) == 2
    assert all(item["speech_region_id"] == "seg_0000" for item in timeline)


def test_overlap_skips_models_and_keeps_one_reviewable_row(tmp_path: Path) -> None:
    sample_rate = 16000
    time = np.arange(sample_rate * 2, dtype=np.float32) / sample_rate
    mixture = (0.1 * (np.sin(2 * np.pi * 220 * time) + np.sin(2 * np.pi * 440 * time))).astype(
        np.float32
    )
    paths = [tmp_path / "a.wav", tmp_path / "b.wav"]
    sf.write(paths[0], mixture, sample_rate)
    sf.write(paths[1], mixture * 0.9, sample_rate)
    config = load_config(Path("configs/default.yaml"))
    config.paths.data_dir = tmp_path / "data"
    config.identity["method"] = "mfcc_knn"
    asr = FakeAsrAdapter(results=[_asr_result("xin chào")] * 2 + [_asr_result("tạm biệt")] * 2)
    separator = _FakeSeparator()
    pipeline = MultiSourceFusionPipeline(
        config,
        asr_adapter=asr,
        segment_extractor=_one_segment,
        turn_detector=_FixedTurns(overlap=True),
        separator=separator,
    )

    run_dir = pipeline.run("Overlapping speakers", paths)
    timeline = json.loads((run_dir / "timeline.json").read_text(encoding="utf-8"))["segments"]
    assert len(timeline) == 1
    row = timeline[0]
    assert row["text"] == ""
    assert row["asr_status"] == "not_run"
    assert row["speaker_count"] == 2
    assert row["overlap_group_id"] == "overlap-1"
    assert row["needs_review"] is True
    assert "overlap_skipped" in row["warnings"]
    assert row["processed_clip_artifact_id"] is None
    assert len(row["original_clip_artifact_ids"]) == 2
    assert all((run_dir / path).is_file() for path in row["original_clip_artifact_ids"])
    assert (run_dir / row["evidence_clip_artifact_id"]).is_file()
    assert asr._call_count == 0
    assert separator.calls == 0
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["models"]["overlap_separation"] == "skipped"
    assert "[Nói chồng: chưa xử lý]" in (run_dir / "exports" / "result.txt").read_text()


def test_bad_reference_asr_cannot_win_fixed_source_fusion(tmp_path: Path) -> None:
    sample_rate = 16000
    time = np.arange(sample_rate * 2, dtype=np.float32) / sample_rate
    signal = (0.1 * np.sin(2 * np.pi * 220 * time)).astype(np.float32)
    paths = [tmp_path / "a.wav", tmp_path / "b.wav"]
    sf.write(paths[0], signal, sample_rate)
    sf.write(paths[1], signal * 0.8, sample_rate)
    config = load_config(Path("configs/default.yaml"))
    config.paths.data_dir = tmp_path / "data"
    config.identity["method"] = "mfcc_knn"
    rejected = AsrResult(
        text="a a a a a",
        words=[],
        status="unreliable",
        warnings=["repeated_word"],
    )
    accepted = AsrResult(
        text="xin chào",
        words=[
            TimedWord(text="xin", start_sec=0.0, end_sec=0.3),
            TimedWord(text="chào", start_sec=0.3, end_sec=0.6),
        ],
        status="transcribed",
    )
    run_dir = MultiSourceFusionPipeline(
        config,
        asr_adapter=FakeAsrAdapter(results=[rejected, accepted]),
        segment_extractor=_one_segment,
        turn_detector=_OneTurnDetector(),
    ).run("Rejected reference", paths, fusion_method="F0_FIXED")

    row = json.loads((run_dir / "timeline.json").read_text())["segments"][0]
    assert row["text"] == "xin chào"
    assert row["asr_status"] == "transcribed"
    assert row["transcript_confidence"] is None
    evidence = {entry["source_id"]: entry for entry in row["source_evidence"]}
    assert evidence["source-1"]["eligible"] is False
    assert evidence["source-1"]["selection_weight"] == 0
    assert evidence["source-2"]["candidate_scores"]["word_agreement"] is None
    assert evidence["source-2"]["candidate_scores"]["asr_confidence"] is None


def test_configured_p3_reaches_artifact_and_timeline(tmp_path: Path, monkeypatch) -> None:
    import meeting_pipeline.pipeline.multi_source_fusion as pipeline_module

    class Encoder:
        def encode(self, waveform):
            vector = np.zeros(192, dtype=np.float32)
            vector[0 if float(np.mean(waveform)) > 0.3 else 1] = 1.0
            return vector

    class Detector:
        def detect(self, aligned_paths, segments, reference_source, duration_sec):
            del aligned_paths, reference_source, duration_sec
            return [
                SpeakerTurn(
                    turn_id="turn_0000",
                    speech_region_id=segments[0].segment_id,
                    start_sec=1.0,
                    end_sec=2.0,
                    track_id="local-1",
                    speaker_count=1,
                    source_activity={
                        sid: {
                            "speech_coverage": 1.0,
                            "local_speaker_purity": 1.0,
                            "support_duration_sec": 1.0,
                            "speech_intervals": [[1.0, 2.0]],
                        }
                        for sid in ("source-1", "source-2")
                    },
                )
            ]

    sample_rate = 16000
    time = np.arange(sample_rate, dtype=np.float32) / sample_rate
    signal_a = np.zeros(sample_rate * 3, dtype=np.float32)
    signal_b = np.zeros(sample_rate * 3, dtype=np.float32)
    signal_a[sample_rate : 2 * sample_rate] = 0.6 + 0.01 * np.sin(2 * np.pi * 220 * time)
    signal_b[sample_rate : 2 * sample_rate] = 0.2 + 0.01 * np.sin(2 * np.pi * 220 * time)
    paths = [tmp_path / "a.wav", tmp_path / "b.wav"]
    sf.write(paths[0], signal_a, sample_rate)
    sf.write(paths[1], signal_b, sample_rate)

    def fake_sync(decoded, sample_rate):
        del sample_rate
        return (
            decoded,
            {
                sid: {
                    "status": "reference" if sid == "source-1" else "aligned",
                    "offset_sec": 0.0,
                    "drift_ppm": 0.0,
                    "residual_ms": 0.0,
                    "valid_coverage_interval": [0.0, 3.0],
                }
                for sid in decoded
            },
            "source-1",
        )

    def one_segment(signals, vad_config, meeting_id, sample_rate):
        del signals, vad_config, sample_rate
        return [
            MeetingSegment(meeting_id=meeting_id, segment_id="seg_0000", start_sec=1.0, end_sec=2.0)
        ]

    monkeypatch.setattr(pipeline_module, "synchronize_multi_source_audio", fake_sync)
    monkeypatch.setattr(pipeline_module, "create_speaker_encoder", lambda **kwargs: Encoder())
    config = load_config(Path("configs/default.yaml"))
    config.paths.data_dir = tmp_path / "data"
    config.identity["fusion_policy"] = "P3_WEIGHTED_SCORE_FUSION"
    profiles = [
        SpeakerProfileInput("alice", "Alice", np.eye(192, dtype=np.float32)[0]),
        SpeakerProfileInput("bob", "Bob", np.eye(192, dtype=np.float32)[1]),
    ]
    run = MultiSourceFusionPipeline(
        config,
        asr_adapter=FakeAsrAdapter(results=[_asr_result("xin chào")] * 2),
        segment_extractor=one_segment,
        turn_detector=Detector(),
    ).run("P3 path", paths, speaker_profiles=profiles)
    decision = json.loads((run / "speaker_decisions.json").read_text())["turns"][0]
    timeline = json.loads((run / "timeline.json").read_text())["segments"][0]
    assert decision["speaker_status"] == "ambiguous"
    assert "source_disagreement" in decision["decision_reason"]
    assert decision["source_evidence"][0]["candidate_cosine_scores"]["alice"] == 1.0
    assert timeline["speaker_status"] == "ambiguous"
    assert timeline["needs_review"] is True
