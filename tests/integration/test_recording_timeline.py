"""Real audio decode/render/fusion with test ASR and no downloaded model weights."""

import json
import math
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from meeting_pipeline.adapters.phowhisper_asr import AsrResult, BaseAsrAdapter
from meeting_pipeline.config import load_config
from meeting_pipeline.domain.contracts import MeetingSegment
from meeting_pipeline.domain.errors import InvalidAudioError
from meeting_pipeline.domain.transcription import TimedWord
from meeting_pipeline.minutes.evidence_retrieval import load_indexed_turns
from meeting_pipeline.pipeline.multi_source_fusion import MultiSourceFusionPipeline
from meeting_pipeline.pipeline.speaker_turns import SpeakerTurn
from meeting_pipeline.pipeline.timeline_audio import TimelineAudioPipeline


class RecordingAsr(BaseAsrAdapter):
    def __init__(self):
        self.inputs = []

    def transcribe(self, waveform, sample_rate=16000):
        self.inputs.append(waveform.copy())
        words = [
            TimedWord(text=text, start_sec=i * 0.3, end_sec=(i + 1) * 0.3, confidence=0.99)
            for i, text in enumerate(["Nội", "dung", "họp"])
        ]
        return AsrResult(text="Nội dung họp", words=words, status="transcribed")


class OneTurn:
    def detect(self, aligned_paths, segments, reference_source, duration_sec, **kwargs):
        return [
            SpeakerTurn(
                turn_id="turn-0",
                speech_region_id="speech-0",
                start_sec=0,
                end_sec=duration_sec,
                track_id="voice-0",
                speaker_count=1,
            )
        ]


def core_factory(asr):
    def factory(config):
        def region(signals, vad_config, meeting_id, sr):
            return [
                MeetingSegment(
                    meeting_id=meeting_id,
                    segment_id="speech-0",
                    start_sec=0,
                    end_sec=max(map(len, signals.values())) / sr,
                )
            ]

        return MultiSourceFusionPipeline(
            config, asr_adapter=asr, segment_extractor=region, turn_detector=OneTurn()
        )

    return factory


def waveform(seconds, seed=42, sr=16000):
    rng = np.random.default_rng(seed)
    return (
        rng.normal(size=seconds * sr) * np.repeat(rng.uniform(0.05, 0.3, seconds * 10), sr // 10)
    ).astype(np.float32)


def setup(tmp_path, waves, placements=None, same_track=False, intervals=None):
    config = load_config(Path("configs/default.yaml"))
    config.paths.data_dir = tmp_path / "data"
    config.identity["method"] = "mfcc_knn"
    config.asr.routing_mode = "all_source"
    config.asr.cache_enabled = False
    paths, clips = {}, []
    for name, samples in waves.items():
        paths[name] = tmp_path / f"{name}.wav"
        sf.write(paths[name], samples, 16000, subtype="FLOAT")
        clips.append(
            {
                "id": name,
                "asset_id": name,
                "source_in_ms": 0,
                "source_out_ms": round(len(samples) / 16),
                "placement": (placements or {}).get(
                    name,
                    {
                        "kind": "sequential",
                        "gap_before_ms": None,
                    },
                ),
            }
        )
    tracks = (
        [{"id": "phone", "clip_ids": list(waves)}]
        if same_track
        else [{"id": name, "clip_ids": [name]} for name in waves]
    )
    return config, paths, {"clips": clips, "tracks": tracks, "intervals": intervals or []}


def test_known_recording_parts_keep_gap_and_original_sample_provenance(tmp_path):
    a, b = waveform(2, 11), waveform(2, 22)
    config, paths, layout = setup(
        tmp_path,
        {"a": a, "b": b},
        {
            "a": {"kind": "anchored", "start_ms": 0},
            "b": {"kind": "sequential", "gap_before_ms": 1000},
        },
        same_track=True,
    )
    asr = RecordingAsr()
    run = TimelineAudioPipeline(config, core_factory(asr)).run("Two parts", paths, layout)
    report = json.loads((run / "alignment.json").read_text())
    rows = json.loads((run / "timeline.json").read_text())["segments"]
    assert report["timing_complete"] is True
    assert len(rows) == 2 and len(asr.inputs) == 2
    assert [(row["start_sec"], row["end_sec"]) for row in rows] == [(0, 2), (3, 5)]
    np.testing.assert_array_equal(asr.inputs[0], a)
    np.testing.assert_array_equal(asr.inputs[1], b)
    assert {value["asset_id"] for row in rows for value in row["recording_evidence"]} == {"a", "b"}
    assert rows[1]["selected_recording_evidence"][0]["source_start_sample"] == 0
    assert rows[1]["selected_recording_evidence"][0]["source_end_sample"] == 32000
    for row in rows:
        assert (run / row["evidence_clip_artifact_id"]).is_file()


@pytest.mark.parametrize("estimated_ms", [1800, 2200])
def test_whole_estimated_file_keeps_actual_decoded_range(tmp_path, monkeypatch, estimated_ms):
    from meeting_pipeline.adapters.audio_io import probe_audio

    samples = waveform(2)
    config, paths, layout = setup(tmp_path, {"a": samples})
    layout["clips"][0]["source_out_ms"] = estimated_ms
    metadata = replace(
        probe_audio(paths["a"]),
        duration_sec=estimated_ms / 1000,
        duration_source="container",
        duration_is_estimate=True,
    )
    monkeypatch.setattr(
        "meeting_pipeline.pipeline.timeline_audio.probe_audio", lambda path: metadata
    )
    asr = RecordingAsr()
    run = TimelineAudioPipeline(config, core_factory(asr)).run("Estimated duration", paths, layout)
    rows = json.loads((run / "timeline.json").read_text())["segments"]
    report = json.loads((run / "alignment.json").read_text())
    np.testing.assert_array_equal(asr.inputs[0], samples)
    assert rows[0]["selected_recording_evidence"][0]["source_end_sample"] == len(samples)
    assert report["warnings"][0]["reason"] == "container_duration_adjusted"
    assert layout["clips"][0]["source_out_ms"] == estimated_ms


@pytest.mark.parametrize("extra_frames", [12, 2, 5, 4])
def test_millisecond_rounded_full_wav_keeps_every_decoded_sample(tmp_path, extra_frames):
    # Reproduce fractional-ms ceil bounds, including a seconds -> samples
    # floating-point edge that must not drop the final sample before ASR.
    samples = waveform(3)[: 32000 + extra_frames]
    config, paths, layout = setup(tmp_path, {"a": samples})
    end_ms = math.ceil(len(samples) * 1000 / 16000)
    layout["clips"][0]["source_out_ms"] = end_ms
    asr = RecordingAsr()
    run = TimelineAudioPipeline(config, core_factory(asr)).run("Rounded full WAV", paths, layout)
    rows = json.loads((run / "timeline.json").read_text())["segments"]
    np.testing.assert_array_equal(asr.inputs[0], samples)
    assert rows[0]["selected_recording_evidence"][0]["source_end_sample"] == len(samples)
    assert layout["clips"][0]["source_out_ms"] == end_ms


def test_range_truly_beyond_decoded_audio_still_fails(tmp_path):
    config, paths, layout = setup(tmp_path, {"a": waveform(2)})
    layout["clips"][0]["source_out_ms"] = 2002
    asr = RecordingAsr()
    with pytest.raises(InvalidAudioError, match="vượt quá thời lượng"):
        TimelineAudioPipeline(config, core_factory(asr)).run("Invalid range", paths, layout)
    assert not asr.inputs


def test_unknown_break_gets_local_transcript_and_cannot_be_used_as_global_minutes(tmp_path):
    config, paths, layout = setup(
        tmp_path, {"a": waveform(2, 11), "b": waveform(2, 22)}, same_track=True
    )
    run = TimelineAudioPipeline(config, core_factory(RecordingAsr())).run(
        "Unknown gap", paths, layout
    )
    manifest = json.loads((run / "manifest.json").read_text())
    rows = json.loads((run / "timeline.json").read_text())["segments"]
    assert manifest["timing_complete"] is False and manifest["duration_sec"] is None
    assert len(rows) == 2
    assert rows[0]["time_status"] == "meeting"
    assert rows[1]["time_status"] == "unresolved"
    assert rows[1]["meeting_start_sec"] is None
    assert rows[1]["start_sec"] == 0
    assert rows[0]["segment_id"] != rows[1]["segment_id"]
    assert rows[0]["meeting_speaker_id"] != rows[1]["meeting_speaker_id"]
    with pytest.raises(ValueError, match="clocks need review"):
        load_indexed_turns(run)
    text = (run / "exports/result.txt").read_text()
    assert "cục bộ" in text


def test_paused_source_does_not_supply_synthetic_padding_to_asr(tmp_path):
    full = waveform(36)
    paused = np.concatenate([full[: 13 * 16000], full[23 * 16000 :]]) * 0.7
    config, paths, layout = setup(tmp_path, {"continuous": full, "paused": paused})
    asr = RecordingAsr()
    run = TimelineAudioPipeline(config, core_factory(asr)).run("Pause", paths, layout)
    report = json.loads((run / "alignment.json").read_text())
    rows = json.loads((run / "timeline.json").read_text())["segments"]
    assert report["timing_complete"] is True
    assert len(report["spans"]["paused"]) == 2
    middle = [row for row in rows if row["start_sec"] >= 13.05 and row["end_sec"] <= 22.95]
    # Exact seam positions are rounded to decoded samples; the entire missing
    # interval can also be one row whose endpoints are approximately 13 and 23.
    middle += [
        row for row in rows if abs(row["start_sec"] - 13) < 0.05 and abs(row["end_sec"] - 23) < 0.05
    ]
    assert middle
    assert all(
        {value["asset_id"] for value in row["recording_evidence"]} == {"continuous"}
        for row in middle
    )
    assert not any(np.max(np.abs(value), initial=0) < 1e-6 for value in asr.inputs)


def test_excluded_interval_is_transcribed_but_not_used_for_minutes(tmp_path):
    config, paths, layout = setup(
        tmp_path,
        {"a": waveform(4)},
        {
            "a": {"kind": "anchored", "start_ms": 0},
        },
        intervals=[{"id": "outside", "kind": "excluded", "start_ms": 1000, "end_ms": 3000}],
    )
    run = TimelineAudioPipeline(config, core_factory(RecordingAsr())).run("Excluded", paths, layout)
    rows = json.loads((run / "timeline.json").read_text())["segments"]
    outside = [row for row in rows if row["excluded_from_minutes"]]
    assert len(outside) == 1 and outside[0]["start_sec"] == 1 and outside[0]["end_sec"] == 3
    indexed = load_indexed_turns(run)
    assert sum(turn.asr_status == "excluded" for turn in indexed) == 1
    assert all(
        not turn.text and not turn.tokens for turn in indexed if turn.asr_status == "excluded"
    )


def test_same_file_selected_as_consecutive_ranges_keeps_original_offsets(tmp_path):
    samples = waveform(4)
    config, paths, layout = setup(
        tmp_path,
        {"a": samples},
        {
            "a": {"kind": "anchored", "start_ms": 0},
        },
    )
    layout["clips"][0]["source_out_ms"] = 2000
    layout["clips"].append(
        {
            "id": "a-second",
            "asset_id": "a",
            "source_in_ms": 2000,
            "source_out_ms": 4000,
            "placement": {"kind": "sequential", "gap_before_ms": 0},
        }
    )
    layout["tracks"][0]["clip_ids"].append("a-second")
    run = TimelineAudioPipeline(config, core_factory(RecordingAsr())).run("Ranges", paths, layout)
    rows = json.loads((run / "timeline.json").read_text())["segments"]
    assert len(rows) == 2
    assert rows[1]["recording_evidence"][0]["source_start_sample"] == 32000
    assert rows[1]["recording_evidence"][0]["source_end_sample"] == 64000


def test_negative_declared_start_shifts_output_origin_without_losing_samples(tmp_path):
    samples = waveform(3)
    config, paths, layout = setup(
        tmp_path,
        {"early": samples},
        {
            "early": {"kind": "anchored", "start_ms": -1000},
        },
    )
    asr = RecordingAsr()
    run = TimelineAudioPipeline(config, core_factory(asr)).run("Early", paths, layout)
    report = json.loads((run / "alignment.json").read_text())
    rows = json.loads((run / "timeline.json").read_text())["segments"]
    assert report["meeting_origin_shift_sec"] == 1
    assert rows[0]["start_sec"] == 0 and rows[0]["end_sec"] == 3
    np.testing.assert_array_equal(asr.inputs[0], samples)
    assert layout["clips"][0]["placement"]["start_ms"] == -1000
