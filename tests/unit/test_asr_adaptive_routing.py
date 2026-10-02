"""Unit tests for WP4: ASR chunking, context windowing, safe turn merging, and adaptive routing."""

from __future__ import annotations

from typing import Any

import numpy as np

from meeting_pipeline.adapters.phowhisper_asr import AsrResult, BaseAsrAdapter
from meeting_pipeline.asr.cache import AsrCache
from meeting_pipeline.asr.segment_asr import transcribe_turn_adaptive
from meeting_pipeline.config import AsrConfig
from meeting_pipeline.domain.transcription import TimedWord
from meeting_pipeline.pipeline.speaker_turns import SpeakerTurn
from meeting_pipeline.pipeline.stages.safe_merge import safe_merge_speaker_turns
from meeting_pipeline.speaker.clustering import TurnAssignment


class MockAsrAdapter(BaseAsrAdapter):
    """Mock ASR adapter producing controlled words with timestamps."""

    def __init__(
        self,
        canned_sequence: list[AsrResult] | None = None,
        default_result: AsrResult | None = None,
    ) -> None:
        self.canned_sequence = list(canned_sequence) if canned_sequence else []
        self.default_result = default_result
        self.call_count = 0

    def transcribe(self, waveform: np.ndarray, sample_rate: int = 16000) -> AsrResult:
        self.call_count += 1
        if self.canned_sequence:
            return self.canned_sequence.pop(0)
        if self.default_result is not None:
            return self.default_result
        return AsrResult(
            text="xin chào các bạn",
            words=[
                TimedWord(text="xin", start_sec=0.1, end_sec=0.3, confidence=0.95),
                TimedWord(text="chào", start_sec=0.3, end_sec=0.6, confidence=0.92),
                TimedWord(text="các", start_sec=0.6, end_sec=0.8, confidence=0.91),
                TimedWord(text="bạn", start_sec=0.8, end_sec=1.1, confidence=0.94),
            ],
            status="transcribed",
            warnings=[],
            raw_candidates=[],
        )


def _make_turn(
    turn_id: str,
    start_sec: float,
    end_sec: float,
    speaker_count: int = 1,
) -> SpeakerTurn:
    return SpeakerTurn(
        turn_id=turn_id,
        start_sec=start_sec,
        end_sec=end_sec,
        speech_region_id="reg-1",
        track_id="trk-1",
        speaker_count=speaker_count,
    )


def _make_assign(turn_id: str, cluster_id: str | None, meeting_spk: str | None) -> TurnAssignment:
    return TurnAssignment(
        turn_id=turn_id,
        cluster_id=cluster_id,
        meeting_speaker_id=meeting_spk,
        speaker_id=cluster_id,
        speaker_label=f"Speaker {cluster_id}" if cluster_id else "Chưa xác định",
        speaker_status="identified" if cluster_id else "unknown",
        decision_reason="mock",
        needs_review=False,
    )


def test_safe_turn_merging_same_cluster() -> None:
    """Consecutive turns in the exact same cluster with small gap are safely merged."""
    turns = [
        _make_turn("t1", 0.0, 2.0),
        _make_turn("t2", 2.3, 4.5),  # gap = 0.3s <= 0.6s -> merge with t1
        _make_turn("t3", 5.0, 7.0),  # different speaker -> do not merge
    ]
    assignments = {
        "t1": _make_assign("t1", "c-0001", "ms-0001"),
        "t2": _make_assign("t2", "c-0001", "ms-0001"),
        "t3": _make_assign("t3", "c-0002", "ms-0002"),
    }

    merged = safe_merge_speaker_turns(turns, assignments, max_merge_gap_sec=0.6, max_core_sec=22.0)

    assert len(merged) == 2
    assert merged[0].turn_id == "merged-t1-t2"
    assert merged[0].start_sec == 0.0
    assert merged[0].end_sec == 4.5
    assert merged[0].sub_turn_ids == ["t1", "t2"]
    assert merged[0].cluster_id == "c-0001"

    assert merged[1].turn_id == "t3"
    assert merged[1].start_sec == 5.0
    assert merged[1].end_sec == 7.0
    assert merged[1].sub_turn_ids == ["t3"]
    assert merged[1].cluster_id == "c-0002"


def test_safe_turn_merging_prevent_across_overlap_or_gap() -> None:
    """Never merge across overlap turns, large gaps (>0.6s) or max core length (>22s)."""
    turns = [
        _make_turn("t1", 0.0, 2.0),
        _make_turn("t2_overlap", 2.0, 3.0, speaker_count=2),
        _make_turn("t3", 3.0, 5.0),
        _make_turn("t4_large_gap", 7.0, 9.0),  # gap = 2.0s > 0.6s
    ]
    assignments = {
        "t1": _make_assign("t1", "c-0001", "ms-0001"),
        "t2_overlap": _make_assign("t2_overlap", None, None),
        "t3": _make_assign("t3", "c-0001", "ms-0001"),
        "t4_large_gap": _make_assign("t4_large_gap", "c-0001", "ms-0001"),
    }

    merged = safe_merge_speaker_turns(turns, assignments, max_merge_gap_sec=0.6, max_core_sec=22.0)

    assert len(merged) == 4
    assert merged[0].turn_id == "t1"
    assert merged[1].turn_id == "t2_overlap"
    assert merged[1].speaker_count == 2
    assert merged[2].turn_id == "t3"
    assert merged[3].turn_id == "t4_large_gap"


def test_adaptive_asr_routing_top1_and_fallback_top2() -> None:
    """Adaptive routing runs top-1, and triggers top-2 only if top-1 is unreliable or margin
    narrow."""
    sr = 16000
    # Create 3 synthetic source signals:
    # mic-1: clean high energy (speech_rms ~ 0.3)
    # mic-2: slightly lower energy (speech_rms ~ 0.15)
    # mic-3: heavy clipping (clipped > 0.99)
    sig1 = np.zeros(sr * 4, dtype=np.float32)
    sig1[sr : 3 * sr] = 0.3

    sig2 = np.zeros(sr * 4, dtype=np.float32)
    sig2[sr : 3 * sr] = 0.15

    sig3 = np.zeros(sr * 4, dtype=np.float32)
    sig3[sr : 3 * sr] = 1.0  # clipped!

    aligned = {"mic-1": sig1, "mic-2": sig2, "mic-3": sig3}
    sync_meta = {
        "mic-1": {"status": "synchronized"},
        "mic-2": {"status": "synchronized"},
        "mic-3": {"status": "synchronized"},
    }

    # Case A: Top-1 succeeds with high margin -> only mic-1 runs, mic-2/3 are not_run
    adapter_clean = MockAsrAdapter()
    config_adapt = AsrConfig(
        model_id="test",
        model_revision="test",
        routing_mode="adaptive",
        adaptive_delta_threshold=0.02,
    )

    hyps, meta = transcribe_turn_adaptive(
        meeting_id="m1",
        turn_id="turn-1",
        core_start_sec=1.0,
        core_end_sec=3.0,
        aligned_signals=aligned,
        sync_metadata=sync_meta,
        asr_adapter=adapter_clean,
        asr_config=config_adapt,
        sample_rate=sr,
    )

    assert meta["scheduled_sources"] == ["mic-1"]
    assert "mic-2" in meta["abstained_sources"]
    assert hyps["mic-1"].asr_status == "transcribed"
    assert hyps["mic-2"].asr_status == "not_run"
    assert hyps["mic-2"].routing_reason == "gated_out_by_adaptive_routing"

    # Case B: Top-1 fails -> automatically schedules top-2
    res_top1 = AsrResult(
        text="", words=[], status="unreliable", warnings=["repeated_ngram"], raw_candidates=[]
    )
    res_top2 = AsrResult(
        text="nguồn hai chạy dự phòng",
        words=[
            TimedWord(text="nguồn", start_sec=0.1, end_sec=0.3, confidence=0.9),
            TimedWord(text="hai", start_sec=0.3, end_sec=0.5, confidence=0.9),
            TimedWord(text="chạy", start_sec=0.5, end_sec=0.7, confidence=0.9),
            TimedWord(text="dự", start_sec=0.7, end_sec=0.9, confidence=0.9),
            TimedWord(text="phòng", start_sec=0.9, end_sec=1.1, confidence=0.9),
        ],
        status="transcribed",
        warnings=[],
        raw_candidates=[],
    )
    adapter_fallback = MockAsrAdapter(canned_sequence=[res_top1, res_top2])

    hyps_fb, meta_fb = transcribe_turn_adaptive(
        meeting_id="m1",
        turn_id="turn-1",
        core_start_sec=1.0,
        core_end_sec=3.0,
        aligned_signals=aligned,
        sync_metadata=sync_meta,
        asr_adapter=adapter_fallback,
        asr_config=config_adapt,
        sample_rate=sr,
    )

    assert "mic-1" in meta_fb["scheduled_sources"]
    assert "mic-2" in meta_fb["scheduled_sources"]
    assert hyps_fb["mic-1"].asr_status == "unreliable"
    assert hyps_fb["mic-2"].asr_status == "transcribed"
    assert "scheduled_fallback_top1_unreliable" in hyps_fb["mic-2"].routing_reason


def test_all_source_routing() -> None:
    """When routing_mode is 'all_source', every eligible source is transcribed."""
    sr = 16000
    sig1 = np.zeros(sr * 3, dtype=np.float32)
    sig1[sr : 2 * sr] = 0.3
    sig2 = np.zeros(sr * 3, dtype=np.float32)
    sig2[sr : 2 * sr] = 0.25

    aligned = {"mic-1": sig1, "mic-2": sig2}
    sync_meta = {"mic-1": {"status": "synchronized"}, "mic-2": {"status": "synchronized"}}

    adapter = MockAsrAdapter()
    config_all = AsrConfig(
        model_id="test",
        model_revision="test",
        routing_mode="all_source",
    )

    hyps, meta = transcribe_turn_adaptive(
        meeting_id="m1",
        turn_id="turn-1",
        core_start_sec=1.0,
        core_end_sec=2.0,
        aligned_signals=aligned,
        sync_metadata=sync_meta,
        asr_adapter=adapter,
        asr_config=config_all,
        sample_rate=sr,
    )

    assert sorted(meta["scheduled_sources"]) == ["mic-1", "mic-2"]
    assert len(meta["abstained_sources"]) == 0
    assert hyps["mic-1"].asr_status == "transcribed"
    assert hyps["mic-2"].asr_status == "transcribed"


def test_context_windowing_and_midpoint_filtering() -> None:
    """Tokens outside core interval are filtered out; tokens on boundary marked uncertain."""
    sr = 16000
    # Core: 2.0s to 4.0s. Context: 0.5s -> Clip is 1.5s to 4.5s (duration 3.0s)
    # Clip local coordinates:
    # 0.0 - 0.5s -> meeting time 1.5 - 2.0s (PRE-CONTEXT)
    # 0.5 - 2.5s -> meeting time 2.0 - 4.0s (CORE)
    # 2.5 - 3.0s -> meeting time 4.0 - 4.5s (POST-CONTEXT)

    res_context = AsrResult(
        text="ngoài biên lõi sau",
        words=[
            # Word 1: in pre-context (midpoint 1.7s < 2.0s core) -> must be discarded
            TimedWord(text="ngoài", start_sec=0.1, end_sec=0.3, confidence=0.9),
            # Word 2: right on core boundary (meeting start 2.02s) -> kept but marked uncertain
            TimedWord(text="biên", start_sec=0.52, end_sec=0.8, confidence=0.9),
            # Word 3: firmly inside core (midpoint 2.7s) -> kept and marked exact
            TimedWord(text="lõi", start_sec=1.0, end_sec=1.4, confidence=0.9),
            # Word 4: in post-context (midpoint 4.25s > 4.0s core) -> must be discarded
            TimedWord(text="sau", start_sec=2.7, end_sec=2.8, confidence=0.9),
        ],
        status="transcribed",
        warnings=[],
        raw_candidates=[],
    )

    adapter = MockAsrAdapter(default_result=res_context)
    sig = np.zeros(sr * 6, dtype=np.float32)
    sig[int(1.5 * sr) : int(4.5 * sr)] = 0.3
    aligned = {"mic-1": sig}

    config = AsrConfig(
        model_id="test",
        model_revision="test",
        chunk_context_seconds=0.5,
    )

    hyps, _meta = transcribe_turn_adaptive(
        meeting_id="m1",
        turn_id="turn-1",
        core_start_sec=2.0,
        core_end_sec=4.0,
        aligned_signals=aligned,
        sync_metadata={"mic-1": {"status": "synchronized"}},
        asr_adapter=adapter,
        asr_config=config,
        sample_rate=sr,
    )

    hyp = hyps["mic-1"]
    assert hyp.text == "biên lõi"
    assert len(hyp.words) == 2
    assert hyp.words[0].word == "biên"
    assert hyp.words[0].time_status == "uncertain"
    assert hyp.words[1].word == "lõi"
    assert hyp.words[1].time_status == "exact"


def test_asr_caching(tmp_path: Any) -> None:
    """ASR cache returns previously computed decode result without calling adapter."""
    cache = AsrCache(cache_dir=tmp_path / "asr_cache", enabled=True)
    sr = 16000
    sig = np.zeros(sr * 3, dtype=np.float32)
    sig[sr : 2 * sr] = 0.25
    aligned = {"mic-1": sig}

    adapter = MockAsrAdapter()
    config = AsrConfig(model_id="test", model_revision="test")

    # Call 1: Cache miss -> adapter is called
    transcribe_turn_adaptive(
        meeting_id="m1",
        turn_id="turn-1",
        core_start_sec=1.0,
        core_end_sec=2.0,
        aligned_signals=aligned,
        sync_metadata={"mic-1": {"status": "synchronized"}},
        asr_adapter=adapter,
        asr_config=config,
        sample_rate=sr,
        cache=cache,
    )
    assert adapter.call_count == 1

    # Call 2: Exact same audio & config -> Cache hit! Adapter call count does not increment
    transcribe_turn_adaptive(
        meeting_id="m1",
        turn_id="turn-1",
        core_start_sec=1.0,
        core_end_sec=2.0,
        aligned_signals=aligned,
        sync_metadata={"mic-1": {"status": "synchronized"}},
        asr_adapter=adapter,
        asr_config=config,
        sample_rate=sr,
        cache=cache,
    )
    assert adapter.call_count == 1
