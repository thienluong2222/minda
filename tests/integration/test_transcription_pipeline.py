"""Integration test for transcription & segmentation pipeline using fake adapters."""

from __future__ import annotations

import csv
import json
import zipfile
from pathlib import Path

import numpy as np
import soundfile as sf

from meeting_pipeline.adapters.phowhisper_asr import AsrResult, FakeAsrAdapter
from meeting_pipeline.config import PipelineConfig, load_config
from meeting_pipeline.domain.schemas import Interval, TimelineSegment
from meeting_pipeline.domain.transcription import (
    AsrChunk,
    ChunkTranscript,
    SpeechRegion,
    TimedWord,
)
from meeting_pipeline.pipeline.prototype import PreparedSource, PrototypePipeline
from meeting_pipeline.pipeline.stages.activity_detection import ActivityDetector


class FakeActivityDetector(ActivityDetector):
    """Stub activity detector returning predetermined speech regions."""

    def __init__(self, regions: list[SpeechRegion]) -> None:
        self._stub_regions = regions

    def detect(
        self,
        sources: list[PreparedSource],
        meeting_duration: float,
    ) -> list[SpeechRegion]:
        return list(self._stub_regions)


def _create_synthetic_wav(path: Path, duration_sec: float, freq: float = 440.0) -> Path:
    sample_rate = 16000
    t = np.linspace(0, duration_sec, int(sample_rate * duration_sec), endpoint=False)
    # Generate smooth amplitude modulated sine wave
    samples = 0.5 * np.sin(2 * np.pi * freq * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 2 * t))
    sf.write(path, samples.astype(np.float32), sample_rate, subtype="PCM_16")
    return path


def test_transcription_pipeline_end_to_end(tmp_path: Path) -> None:
    # 1. Prepare configuration pointing to isolated test directories
    config_path = Path("configs/default.yaml")
    config: PipelineConfig = load_config(config_path)
    config.paths.data_dir = tmp_path / "data"
    config.paths.database_path = tmp_path / "data" / "app.sqlite"
    config.paths.model_cache_dir = tmp_path / "models"
    config.identity["method"] = "mfcc_knn"

    # 2. Create synthetic audio sources
    audio_dir = tmp_path / "input_audio"
    audio_dir.mkdir(parents=True)
    source1_path = _create_synthetic_wav(audio_dir / "mic1.wav", duration_sec=5.0, freq=300.0)
    source2_path = _create_synthetic_wav(audio_dir / "mic2.wav", duration_sec=5.0, freq=500.0)

    # 3. Create stub speech regions:
    #    - Region 1: Single speaker (0.5s to 3.5s)
    #    - Region 2: Overlap speech (3.8s to 4.8s, speaker_count=2)
    regions = [
        SpeechRegion(
            region_id="reg-single-1",
            start_sec=0.5,
            end_sec=3.5,
            supporting_source_ids=["source-1", "source-2"],
            source_intervals={
                "source-1": Interval(start_sec=0.5, end_sec=3.5),
                "source-2": Interval(start_sec=0.5, end_sec=3.5),
            },
            speaker_count=1,
            warnings=[],
        ),
        SpeechRegion(
            region_id="reg-overlap-2",
            start_sec=3.8,
            end_sec=4.8,
            supporting_source_ids=["source-1", "source-2"],
            source_intervals={
                "source-1": Interval(start_sec=3.8, end_sec=4.8),
                "source-2": Interval(start_sec=3.8, end_sec=4.8),
            },
            speaker_count=2,
            warnings=[],
        ),
    ]
    fake_detector = FakeActivityDetector(regions)

    # 4. Create Fake ASR adapter with canned Vietnamese words
    canned_words = [
        TimedWord(text="kính", start_sec=0.6, end_sec=0.9),
        TimedWord(text="chào", start_sec=1.0, end_sec=1.3),
        TimedWord(text="quý", start_sec=1.4, end_sec=1.7),
        TimedWord(text="vị.", start_sec=1.8, end_sec=2.1),
        TimedWord(text="cuộc", start_sec=2.3, end_sec=2.5),
        TimedWord(text="họp", start_sec=2.6, end_sec=2.8),
        TimedWord(text="bắt", start_sec=2.9, end_sec=3.1),
        TimedWord(text="đầu.", start_sec=3.2, end_sec=3.4),
    ]
    fake_asr = FakeAsrAdapter(
        default_result=AsrResult(
            text="kính chào quý vị. cuộc họp bắt đầu.",
            words=canned_words,
            status="transcribed",
        )
    )

    # 5. Initialize pipeline with injected fake components
    pipeline = PrototypePipeline(
        config=config,
        activity_detector=fake_detector,
        asr_adapter=fake_asr,
    )

    # Mock separation for the overlap region so no model download is triggered
    sample_rate = config.audio.analysis_sample_rate

    def _mock_separate(mixture: np.ndarray) -> list[np.ndarray]:
        track1 = mixture * 0.8
        track2 = mixture * 0.6
        return [track1.astype(np.float32), track2.astype(np.float32)]

    pipeline._separate = _mock_separate  # type: ignore[assignment]

    # 6. Run pipeline
    run_dir = pipeline.run(
        meeting_name="Integration Test Meeting",
        source_paths=[source1_path, source2_path],
    )
    assert run_dir.is_dir()

    # 7. Check Stage A artifact: activity_regions.json
    act_file = run_dir / "activity_regions.json"
    assert act_file.is_file()
    act_data = json.loads(act_file.read_text(encoding="utf-8"))
    assert act_data["schema_version"] == "1.0"
    assert len(act_data["regions"]) == 2
    for r_dict in act_data["regions"]:
        SpeechRegion.model_validate(r_dict)

    # 8. Check Stage B artifact: asr_chunks.json and clips/asr-input
    chunk_file = run_dir / "asr_chunks.json"
    assert chunk_file.is_file()
    chunk_data = json.loads(chunk_file.read_text(encoding="utf-8"))
    assert len(chunk_data["chunks"]) >= 1
    for c_dict in chunk_data["chunks"]:
        chunk = AsrChunk.model_validate(c_dict)
        chunk_wav = run_dir / chunk.clip_artifact_id
        assert chunk_wav.is_file()
        info = sf.info(chunk_wav)
        assert info.samplerate == sample_rate
        assert info.channels == 1

    # 9. Check Stage C artifact: chunk_transcripts.json
    ct_file = run_dir / "chunk_transcripts.json"
    assert ct_file.is_file()
    ct_data = json.loads(ct_file.read_text(encoding="utf-8"))
    assert len(ct_data["transcripts"]) >= 1
    for ct_dict in ct_data["transcripts"]:
        ChunkTranscript.model_validate(ct_dict)

    # 10. Check Stage D artifact: stitched_transcript.json
    stitch_file = run_dir / "stitched_transcript.json"
    assert stitch_file.is_file()
    stitch_data = json.loads(stitch_file.read_text(encoding="utf-8"))
    assert len(stitch_data["words"]) > 0
    assert "kính chào" in stitch_data["full_text"]

    # 11. Check Stage E & F artifacts: timeline.json & clips/evidence
    timeline_file = run_dir / "timeline.json"
    assert timeline_file.is_file()
    timeline_data = json.loads(timeline_file.read_text(encoding="utf-8"))
    segments = timeline_data["segments"]
    assert len(segments) >= 2  # at least sentence(s) from single-speaker + 2 overlap tracks

    # Check each timeline segment against schema and invariants
    prev_start = -1.0
    for seg_dict in segments:
        seg = TimelineSegment.model_validate(seg_dict)
        assert seg.start_sec >= prev_start
        prev_start = seg.start_sec

        # Check evidence clip
        assert seg.evidence_clip_artifact_id is not None
        ev_path = run_dir / seg.evidence_clip_artifact_id
        assert ev_path.is_file()
        ev_info = sf.info(ev_path)
        assert ev_info.samplerate == sample_rate
        assert ev_info.channels == 1
        assert ev_info.duration > 0.0

        # Check provenance
        assert seg.provenance is not None
        assert len(seg.provenance.original_spans) >= 1
        assert seg.provenance.speech_interval.end_sec > seg.provenance.speech_interval.start_sec
        assert seg.provenance.clip_interval.end_sec > seg.provenance.clip_interval.start_sec
        assert len(seg.provenance.transform_chain) > 0
        assert seg.provenance.asr_model_revision is not None

        # Check overlap vs single speaker attributes
        if seg.overlap_group_id is not None:
            assert seg.needs_review is True
        else:
            assert seg.speech_region_id == "reg-single-1"
            assert len(seg.asr_chunk_ids) > 0

    # 12. Check Exports consistency (JSON, CSV, TXT, ZIP)
    exports_dir = run_dir / "exports"
    result_json = exports_dir / "result.json"
    result_csv = exports_dir / "result.csv"
    result_txt = exports_dir / "result.txt"
    result_zip = exports_dir / "result.zip"

    assert result_json.is_file()
    assert result_csv.is_file()
    assert result_txt.is_file()
    assert result_zip.is_file()

    # CSV validation
    with result_csv.open("r", encoding="utf-8") as f:
        reader = list(csv.reader(f))
        assert len(reader) >= 1
        header = reader[0]
        assert header == [
            "start_sec",
            "end_sec",
            "speaker_status",
            "speaker_id",
            "speaker_label",
            "text",
            "source_id",
        ]
        data_rows = reader[1:]
        assert len(data_rows) == len(segments)

        for row, seg in zip(data_rows, segments, strict=True):
            assert float(row[0]) == float(seg["start_sec"])
            assert float(row[1]) == float(seg["end_sec"])
            assert row[2] == seg["speaker_status"]
            # Verify speaker_id column does NOT contain display label
            if seg.get("speaker_id"):
                assert row[3] == str(seg["speaker_id"])
            else:
                assert row[3] == ""
            assert row[4] == str(seg.get("speaker_label") or "")
            assert row[5] == seg["text"]

    # TXT validation
    raw_txt = result_txt.read_text(encoding="utf-8").strip()
    txt_lines = [line.strip() for line in raw_txt.splitlines()]
    assert len(txt_lines) == len(segments)

    # ZIP archive contents validation
    with zipfile.ZipFile(result_zip, "r") as archive:
        namelist = archive.namelist()
        assert "activity_regions.json" in namelist
        assert "asr_chunks.json" in namelist
        assert "chunk_transcripts.json" in namelist
        assert "stitched_transcript.json" in namelist
        assert "timeline.json" in namelist
        assert "coverage.json" in namelist
        assert any(name.startswith("clips/evidence/") for name in namelist)
        assert any(name.startswith("clips/asr-input/") for name in namelist)


def test_transcription_pipeline_silence(tmp_path: Path) -> None:
    """When no speech is detected, pipeline completes cleanly with empty timeline."""
    config: PipelineConfig = load_config(Path("configs/default.yaml"))
    config.paths.data_dir = tmp_path / "data"
    config.paths.database_path = tmp_path / "data" / "app.sqlite"
    config.paths.model_cache_dir = tmp_path / "models"
    config.identity["method"] = "mfcc_knn"

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True)
    src_path = _create_synthetic_wav(audio_dir / "silence.wav", duration_sec=3.0, freq=440.0)

    fake_detector = FakeActivityDetector([])  # No speech regions
    fake_asr = FakeAsrAdapter(
        default_result=AsrResult(text="", words=[], status="empty", warnings=["empty_audio"])
    )

    pipeline = PrototypePipeline(
        config=config,
        activity_detector=fake_detector,
        asr_adapter=fake_asr,
    )

    run_dir = pipeline.run("Silence Meeting", [src_path])
    assert run_dir.is_dir()

    act_data = json.loads((run_dir / "activity_regions.json").read_text(encoding="utf-8"))
    assert act_data["regions"] == []

    chunk_data = json.loads((run_dir / "asr_chunks.json").read_text(encoding="utf-8"))
    assert chunk_data["chunks"] == []

    ct_data = json.loads((run_dir / "chunk_transcripts.json").read_text(encoding="utf-8"))
    assert ct_data["transcripts"] == []

    stitch_data = json.loads((run_dir / "stitched_transcript.json").read_text(encoding="utf-8"))
    assert stitch_data["words"] == []
    assert stitch_data["full_text"] == ""

    timeline_data = json.loads((run_dir / "timeline.json").read_text(encoding="utf-8"))
    assert timeline_data["segments"] == []

    result_csv = run_dir / "exports" / "result.csv"
    with result_csv.open("r", encoding="utf-8") as f:
        reader = list(csv.reader(f))
        assert len(reader) == 1  # Only header
