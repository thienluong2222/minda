"""Unit tests for WP1: Shared Pyannote VAD (Option B), caching and turn integration."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from meeting_pipeline.adapters.pyannote_segmentation import (
    SegmentationResult,
    SlidingWindow,
)
from meeting_pipeline.domain.contracts import VadConfig
from meeting_pipeline.pipeline.speaker_turns import SpeakerTurnDetector
from meeting_pipeline.pipeline.stages.shared_segmentation import (
    compute_pyannote_activity_curve,
    extract_pyannote_vad_intervals,
    run_shared_pyannote_segmentation,
)


class MockSegmentationAdapter:
    """Mock adapter tracking call counts to verify single-inference per source invariant."""

    def __init__(
        self,
        data_by_source: dict[str, np.ndarray],
        duration: float = 10.0,
        step: float = 2.5,
    ) -> None:
        self.data_by_source = data_by_source
        self.duration = duration
        self.step = step
        self.call_counts: dict[str, int] = {}

    def segment_file(self, path: Path, source_id: str = "") -> SegmentationResult:
        sid = source_id or path.stem
        self.call_counts[sid] = self.call_counts.get(sid, 0) + 1
        data = self.data_by_source.get(sid, np.zeros((1, 593, 3), dtype=np.float32))
        return SegmentationResult(
            data=data,
            sliding_window=SlidingWindow(duration=self.duration, step=self.step),
            source_id=sid,
            audio_hash=f"hash_{sid}",
            step_seconds=self.step,
            duration_sec=self.duration,
            frame_step=self.duration / max(1, data.shape[1]),
        )


def test_single_inference_per_source_call_count(tmp_path: Path) -> None:
    """Verify pyannote is executed exactly ONCE per source and reused for turns."""
    data = np.zeros((2, 100, 3), dtype=np.float32)
    # Speech in first chunk channel 0
    data[0, 10:50, 0] = 0.9

    adapter = MockSegmentationAdapter({"dev-1": data, "dev-2": data})
    aligned_paths = {"dev-1": tmp_path / "dev-1.wav", "dev-2": tmp_path / "dev-2.wav"}
    vad_cfg = VadConfig(threshold=0.5, min_speech_sec=0.25, merge_gap_sec=0.4, padding_sec=0.1)

    segments, cached_results = run_shared_pyannote_segmentation(
        aligned_paths=aligned_paths,
        adapter=adapter,  # type: ignore[arg-type]
        meeting_duration_sec=10.0,
        vad_config=vad_cfg,
        meeting_id="test_meeting",
    )

    assert len(segments) > 0
    # Exactly one call per source during VAD
    assert adapter.call_counts["dev-1"] == 1
    assert adapter.call_counts["dev-2"] == 1

    # Turn detector must reuse cached_results without re-running inference
    detector = SpeakerTurnDetector(tmp_path / "model.bin", step_seconds=2.5, adapter=adapter)  # type: ignore[arg-type]
    turns = detector.detect(
        aligned_paths,
        segments,
        reference_source="dev-1",
        duration_sec=10.0,
        cached_results=cached_results,
    )

    assert len(turns) > 0
    # Call counts must remain 1!
    assert adapter.call_counts["dev-1"] == 1
    assert adapter.call_counts["dev-2"] == 1


def test_vad_activity_curve_and_intervals() -> None:
    """Test frame activity conversion and interval generation."""
    # 1 chunk, 100 frames, duration=10.0s -> 0.1s/frame
    data = np.zeros((1, 100, 3), dtype=np.float32)
    # 2.0s to 4.0s: frames 20 to 40 active on channel 1
    data[0, 20:40, 1] = 0.85

    res = SegmentationResult(
        data=data,
        sliding_window=SlidingWindow(duration=10.0, step=2.5),
        source_id="src-1",
        duration_sec=10.0,
        frame_step=0.1,
    )

    curve = compute_pyannote_activity_curve(res, meeting_duration_sec=10.0, bin_sec=0.05)
    assert len(curve) == 200
    assert np.max(curve[40:80]) > 0.7
    assert np.max(curve[:30]) < 0.1

    intervals = extract_pyannote_vad_intervals(
        curve,
        bin_sec=0.05,
        threshold=0.5,
        min_speech_ms=250,
        merge_gap_ms=400,
        speech_pad_ms=100,
    )
    assert len(intervals) == 1
    s, e = intervals[0]
    assert 1.8 <= s <= 2.1
    assert 3.9 <= e <= 4.2


def test_failed_alignment_source_excluded(tmp_path: Path) -> None:
    """A source with status alignment_failed is excluded from VAD voting."""
    data_good = np.zeros((1, 100, 3), dtype=np.float32)
    data_good[0, 20:50, 0] = 0.9

    data_bad = np.ones((1, 100, 3), dtype=np.float32) * 0.9  # Constant noisy hallucination

    adapter = MockSegmentationAdapter({"good": data_good, "bad": data_bad})
    aligned_paths = {"good": tmp_path / "good.wav", "bad": tmp_path / "bad.wav"}
    sync_metadata = {
        "good": {"status": "aligned", "offset_sec": 0.0, "residual_ms": 1.0},
        "bad": {"status": "alignment_failed", "offset_sec": 0.0, "residual_ms": 999.0},
    }

    segments, cached = run_shared_pyannote_segmentation(
        aligned_paths=aligned_paths,
        adapter=adapter,  # type: ignore[arg-type]
        meeting_duration_sec=10.0,
        vad_config=VadConfig(threshold=0.5),
        meeting_id="m",
        sync_metadata=sync_metadata,
    )

    # Bad source was excluded, so only 'good' was queried and counted
    assert "bad" not in cached
    assert "good" in cached
    assert len(segments) == 1


def test_silence_creates_no_false_alarm(tmp_path: Path) -> None:
    """Silence input generates empty activity and zero speech segments."""
    data = np.zeros((2, 100, 3), dtype=np.float32)
    adapter = MockSegmentationAdapter({"dev": data})
    aligned_paths = {"dev": tmp_path / "dev.wav"}

    segments, _ = run_shared_pyannote_segmentation(
        aligned_paths=aligned_paths,
        adapter=adapter,  # type: ignore[arg-type]
        meeting_duration_sec=10.0,
        vad_config=VadConfig(threshold=0.5),
        meeting_id="m",
    )
    assert len(segments) == 0


def test_two_speakers_overlap_creates_turn_overlap_flag(tmp_path: Path) -> None:
    """When two channels are simultaneously active, speaker_count=2 and overlap_group_id is set."""
    data = np.zeros((1, 100, 3), dtype=np.float32)
    # Overlapping speech between frame 30 and 60
    data[0, 20:60, 0] = 0.95  # Speaker 1
    data[0, 35:70, 1] = 0.95  # Speaker 2

    adapter = MockSegmentationAdapter({"dev-1": data})
    aligned_paths = {"dev-1": tmp_path / "dev-1.wav"}
    vad_cfg = VadConfig(threshold=0.5, padding_sec=0.0)

    segments, cached = run_shared_pyannote_segmentation(
        aligned_paths=aligned_paths,
        adapter=adapter,  # type: ignore[arg-type]
        meeting_duration_sec=10.0,
        vad_config=vad_cfg,
        meeting_id="m",
    )

    detector = SpeakerTurnDetector(tmp_path / "m.bin", 2.5, adapter)  # type: ignore[arg-type]
    turns = detector.detect(
        aligned_paths,
        segments,
        reference_source="dev-1",
        duration_sec=10.0,
        cached_results=cached,
    )

    # Overlap interval must have speaker_count == 2
    overlap_turns = [t for t in turns if t.speaker_count == 2]
    assert len(overlap_turns) > 0
    assert all(t.overlap_group_id is not None for t in overlap_turns)
