"""Ablation matrix benchmarking script (WP7).

Executes A0 to A7 ablations and benchmarks timing, ASR calls, speaker clustering,
and transcript fusion.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import numpy as np

from meeting_pipeline.adapters.phowhisper_asr import AsrResult, BaseAsrAdapter, TimedWord
from meeting_pipeline.domain.contracts import (
    SourceHypothesis,
    WordHypothesis,
)
from meeting_pipeline.fusion.baselines import (
    fuse_f0_fixed,
    fuse_f1_best_segment,
    fuse_f3_rover,
    fuse_f4_asr_weighted,
    fuse_f5_rule_weighted,
    fuse_f5_rule_weighted_corrected,
)
from meeting_pipeline.fusion.confusion_network import build_confusion_network
from meeting_pipeline.pipeline.speaker_turns import SpeakerTurn, SpeakerTurnDetector
from meeting_pipeline.pipeline.stages.shared_segmentation import run_shared_pyannote_segmentation
from meeting_pipeline.speaker.clustering import GlobalSpeakerClusterer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ablation_benchmark")


class MockCountingAsr(BaseAsrAdapter):
    """Counting mock ASR for reproducible, fast timing ablation."""

    def __init__(self) -> None:
        self.call_count = 0
        self.total_audio_sec = 0.0

    def transcribe(
        self,
        waveform: np.ndarray,
        sample_rate: int = 16000,
        initial_prompt: str | None = None,
    ) -> AsrResult:
        self.call_count += 1
        dur = len(waveform) / sample_rate
        self.total_audio_sec += dur
        # Simulate slight inference time: ~5ms per second of audio
        time.sleep(dur * 0.005)
        return AsrResult(
            text="kính thưa các đồng chí cuộc họp hôm nay bắt đầu",
            words=[
                TimedWord(text="kính", start_sec=0.1, end_sec=0.4),
                TimedWord(text="thưa", start_sec=0.4, end_sec=0.7),
                TimedWord(text="các", start_sec=0.7, end_sec=0.9),
                TimedWord(text="đồng", start_sec=0.9, end_sec=1.1),
                TimedWord(text="chí", start_sec=1.1, end_sec=1.4),
                TimedWord(text="cuộc", start_sec=1.5, end_sec=1.8),
                TimedWord(text="họp", start_sec=1.8, end_sec=2.1),
                TimedWord(text="hôm", start_sec=2.1, end_sec=2.3),
                TimedWord(text="nay", start_sec=2.3, end_sec=2.6),
                TimedWord(text="bắt", start_sec=2.6, end_sec=2.8),
                TimedWord(text="đầu", start_sec=2.8, end_sec=3.1),
            ],
            status="transcribed",
        )


def benchmark_shared_segmentation_vs_legacy(
    sources: dict[str, np.ndarray], sr: int, run_dir: Path
) -> dict[str, Any]:
    """Compare Option B (shared segmentation) vs legacy repeated segmentation."""
    import soundfile as sf

    from meeting_pipeline.adapters.pyannote_segmentation import (
        SegmentationResult,
        SlidingWindow,
    )
    from meeting_pipeline.domain.contracts import VadConfig

    run_dir.mkdir(parents=True, exist_ok=True)
    aligned_paths: dict[str, Path] = {}
    for sid, wave in sources.items():
        p = run_dir / f"{sid}.wav"
        sf.write(p, wave, sr)
        aligned_paths[sid] = p

    mock_data = {sid: np.zeros((2, 100, 3), dtype=np.float32) for sid in sources}
    for sid in mock_data:
        mock_data[sid][0, 10:50, 0] = 0.9

    class MockAdapter:
        def __init__(self) -> None:
            self.calls = 0

        def segment_file(self, path: Path, source_id: str = "") -> SegmentationResult:
            self.calls += 1
            sid = source_id or path.stem
            time.sleep(0.01)  # simulate inference
            return SegmentationResult(
                data=mock_data.get(sid, np.zeros((1, 593, 3), dtype=np.float32)),
                sliding_window=SlidingWindow(duration=10.0, step=2.5),
                source_id=sid,
                audio_hash=f"hash_{sid}",
                step_seconds=2.5,
                duration_sec=10.0,
                frame_step=10.0 / 100,
            )

        def save_npz(self, path: Path, result: SegmentationResult) -> None:
            from meeting_pipeline.adapters.pyannote_segmentation import PyannoteSegmentationAdapter

            PyannoteSegmentationAdapter.save_npz(self, path, result)  # type: ignore[arg-type]

        def load_npz(self, path: Path) -> SegmentationResult:
            from meeting_pipeline.adapters.pyannote_segmentation import PyannoteSegmentationAdapter

            return PyannoteSegmentationAdapter.load_npz(self, path)  # type: ignore[arg-type]

    adapter_b = MockAdapter()
    vad_cfg = VadConfig(threshold=0.5, min_speech_sec=0.25, merge_gap_sec=0.4, padding_sec=0.1)

    t0 = time.perf_counter()
    vad_segs, seg_results = run_shared_pyannote_segmentation(
        aligned_paths=aligned_paths,
        adapter=adapter_b,  # type: ignore[arg-type]
        meeting_duration_sec=10.0,
        vad_config=vad_cfg,
        meeting_id="bench_m",
        run_dir=run_dir,
    )
    turn_detector = SpeakerTurnDetector(
        checkpoint=Path("dummy"),
        step_seconds=2.5,
        adapter=adapter_b,  # type: ignore[arg-type]
    )
    ref_src = next(iter(aligned_paths.keys()))
    turns = turn_detector.detect(
        aligned_paths=aligned_paths,
        segments=vad_segs,
        reference_source=ref_src,
        duration_sec=10.0,
        cached_results=seg_results,
    )
    t_shared = time.perf_counter() - t0

    # In legacy option A, segmentation was called once for VAD and once again for turns
    t_legacy_est = t_shared * 2.0

    return {
        "shared_vad_time_sec": round(t_shared, 4),
        "legacy_vad_time_sec": round(t_legacy_est, 4),
        "speedup_ratio": round(t_legacy_est / max(t_shared, 1e-6), 2),
        "total_sources": len(sources),
        "vad_regions_found": len(vad_segs),
        "speaker_turns_found": len(turns),
        "pyannote_inferences_option_b": adapter_b.calls,
        "pyannote_inferences_legacy": adapter_b.calls * 2,
    }


def benchmark_speaker_clustering_stability() -> dict[str, Any]:
    """Benchmark GlobalSpeakerClusterer consistency on synthetic multi-turn dialogue."""

    class DummyBenchmarkEncoder:
        def __init__(self, dimension: int = 192) -> None:
            self.embedding_dimension = dimension
            self.model_id = "mock-encoder"
            self.revision = "v1"

        def encode(self, waveform: np.ndarray) -> np.ndarray:
            mean_val = float(np.mean(waveform))
            vec = np.zeros(self.embedding_dimension, dtype=np.float32)
            if abs(mean_val - 0.2) < 0.1:
                vec[0] = 1.0
            elif abs(mean_val - 0.5) < 0.1:
                vec[1] = 1.0
            else:
                vec[0] = 1.0
            norm = float(np.linalg.norm(vec))
            if norm > 1e-8:
                vec /= norm
            return vec

    encoder = DummyBenchmarkEncoder()
    clusterer = GlobalSpeakerClusterer(
        encoder=encoder,  # type: ignore[arg-type]
        cluster_threshold=0.40,
        assign_threshold=0.35,
        assign_margin=0.05,
    )
    sr = 16000

    # Generate 6 turns alternating between 2 unknown speakers: A, B, A, B, A, B
    time_vec = np.arange(sr * 2, dtype=np.float32) / sr
    sig_spk_a = (0.2 + 0.05 * np.sin(2 * np.pi * 180 * time_vec)).astype(np.float32)
    sig_spk_b = (0.5 + 0.05 * np.sin(2 * np.pi * 320 * time_vec)).astype(np.float32)

    turns = [
        SpeakerTurn(
            turn_id="t1",
            speech_region_id="r1",
            start_sec=0.0,
            end_sec=2.0,
            track_id="track_0",
            speaker_count=1,
        ),
        SpeakerTurn(
            turn_id="t2",
            speech_region_id="r1",
            start_sec=2.5,
            end_sec=4.5,
            track_id="track_0",
            speaker_count=1,
        ),
        SpeakerTurn(
            turn_id="t3",
            speech_region_id="r2",
            start_sec=5.0,
            end_sec=7.0,
            track_id="track_0",
            speaker_count=1,
        ),
        SpeakerTurn(
            turn_id="t4",
            speech_region_id="r2",
            start_sec=7.5,
            end_sec=9.5,
            track_id="track_0",
            speaker_count=1,
        ),
        SpeakerTurn(
            turn_id="t5",
            speech_region_id="r3",
            start_sec=10.0,
            end_sec=12.0,
            track_id="track_0",
            speaker_count=1,
        ),
        SpeakerTurn(
            turn_id="t6",
            speech_region_id="r3",
            start_sec=12.5,
            end_sec=14.5,
            track_id="track_0",
            speaker_count=1,
        ),
    ]
    # In aligned signals, odd turns are spk A, even turns are spk B
    full_len = sr * 15
    aligned_a = np.zeros(full_len, dtype=np.float32)
    aligned_b = np.zeros(full_len, dtype=np.float32)

    for i, t in enumerate(turns):
        s_idx = int(t.start_sec * sr)
        e_idx = int(t.end_sec * sr)
        sig = sig_spk_a if i % 2 == 0 else sig_spk_b
        aligned_a[s_idx:e_idx] = sig
        aligned_b[s_idx:e_idx] = sig * 0.9

    aligned_signals = {"mic1": aligned_a, "mic2": aligned_b}

    assignments, _, summary = clusterer.cluster_and_identify(
        turns=turns,
        aligned_signals=aligned_signals,
        sample_rate=sr,
        profiles=[],  # 0 enrolled profiles
    )

    labels = [assignments[t.turn_id].speaker_label for t in turns]
    meeting_ids = [assignments[t.turn_id].meeting_speaker_id for t in turns]

    # Speaker A turns should all have label "Người lạ 1"
    spk_a_labels = {labels[0], labels[2], labels[4]}
    # Speaker B turns should all have label "Người lạ 2"
    spk_b_labels = {labels[1], labels[3], labels[5]}

    is_stable = len(spk_a_labels) == 1 and len(spk_b_labels) == 1 and spk_a_labels != spk_b_labels

    return {
        "zero_enrollment_handled": True,
        "cluster_count": summary["total_clusters"],
        "speaker_a_stable_label": next(iter(spk_a_labels)),
        "speaker_b_stable_label": next(iter(spk_b_labels)),
        "labels_sequence": labels,
        "meeting_speaker_ids": meeting_ids,
        "is_stable": is_stable,
    }


def benchmark_asr_routing_efficiency() -> dict[str, Any]:
    """Benchmark ASR call reduction with Adaptive Routing vs All-source."""
    from meeting_pipeline.asr.router import AdaptiveAsrRouter, evaluate_source_pre_quality_for_asr

    sr = 16000

    # 4 sources: 1 clean, 1 medium, 1 clipped, 1 heavy silence/dropout
    t_clean = (0.2 * np.random.randn(sr * 3)).astype(np.float32)
    t_med = (0.1 * np.random.randn(sr * 3)).astype(np.float32)
    t_clipped = np.clip(0.8 * np.random.randn(sr * 3), -0.3, 0.3).astype(np.float32)
    t_dropout = np.zeros(sr * 3, dtype=np.float32)
    t_dropout[:100] = 0.05

    candidate_signals = {
        "src1_clean": t_clean,
        "src2_med": t_med,
        "src3_clipped": t_clipped,
        "src4_dropout": t_dropout,
    }

    evals = {
        sid: evaluate_source_pre_quality_for_asr(
            source_id=sid,
            turn_waveform=sig,
            sample_rate=sr,
        )
        for sid, sig in candidate_signals.items()
    }

    router_adapt = AdaptiveAsrRouter(mode="adaptive")
    ranked = router_adapt.rank_sources(evals)
    adaptive_sources = router_adapt.select_initial_sources(ranked)

    router_all = AdaptiveAsrRouter(mode="all_source")
    all_sources = router_all.select_initial_sources(ranked)

    all_source_calls = len(all_sources)
    adaptive_calls = len(adaptive_sources)
    saved_calls = all_source_calls - adaptive_calls
    reduction_pct = round((saved_calls / max(1, all_source_calls)) * 100, 1)

    abstained = [sid for sid in candidate_signals if sid not in adaptive_sources]

    return {
        "total_sources": len(candidate_signals),
        "transcribed_sources": adaptive_sources,
        "abstained_sources": abstained,
        "calls_all_source": all_source_calls,
        "calls_adaptive": adaptive_calls,
        "saved_calls": saved_calls,
        "reduction_percentage": f"{reduction_pct}%",
    }


def benchmark_fusion_methods_cer_proxy() -> dict[str, Any]:
    """Compare CER/WER proxy across fusion baselines F0, F1, F3, F5, F5_CORRECTED."""
    # Synthetic scenario: Primary source heard correct text, secondary heard noisy hallucination
    # Source A (Clean): "kính thưa các đồng chí"
    # Source B (Noisy): "kính thưa các đồng chí thêm từ ảo giác"
    # Source C (Dropout): "" (abstained)
    hyp_a = SourceHypothesis(
        meeting_id="m",
        segment_id="s",
        source_id="src_a",
        text="kính thưa các đồng chí",
        transcript_quality_score=0.92,
        words=[
            WordHypothesis(word="kính", start_sec=0.0, end_sec=0.3, asr_confidence=0.95),
            WordHypothesis(word="thưa", start_sec=0.3, end_sec=0.6, asr_confidence=0.95),
            WordHypothesis(word="các", start_sec=0.6, end_sec=0.8, asr_confidence=0.95),
            WordHypothesis(word="đồng", start_sec=0.8, end_sec=1.1, asr_confidence=0.95),
            WordHypothesis(word="chí", start_sec=1.1, end_sec=1.4, asr_confidence=0.95),
        ],
    )
    hyp_b = SourceHypothesis(
        meeting_id="m",
        segment_id="s",
        source_id="src_b",
        text="kính thưa các đồng chí thêm từ ảo giác",
        transcript_quality_score=0.60,
        words=[
            WordHypothesis(word="kính", start_sec=0.0, end_sec=0.3, asr_confidence=0.7),
            WordHypothesis(word="thưa", start_sec=0.3, end_sec=0.6, asr_confidence=0.7),
            WordHypothesis(word="các", start_sec=0.6, end_sec=0.8, asr_confidence=0.7),
            WordHypothesis(word="đồng", start_sec=0.8, end_sec=1.1, asr_confidence=0.7),
            WordHypothesis(word="chí", start_sec=1.1, end_sec=1.4, asr_confidence=0.7),
            WordHypothesis(word="thêm", start_sec=1.5, end_sec=1.8, asr_confidence=0.4),
            WordHypothesis(word="từ", start_sec=1.8, end_sec=2.0, asr_confidence=0.4),
            WordHypothesis(word="ảo", start_sec=2.0, end_sec=2.3, asr_confidence=0.4),
            WordHypothesis(word="giác", start_sec=2.3, end_sec=2.6, asr_confidence=0.4),
        ],
    )
    hyp_c = SourceHypothesis(
        meeting_id="m",
        segment_id="s",
        source_id="src_c",
        text="",
        asr_status="not_run",
        transcript_quality_score=0.0,
    )

    hypotheses = {"src_a": hyp_a, "src_b": hyp_b, "src_c": hyp_c}
    bins = build_confusion_network(hypotheses)

    ground_truth = "kính thưa các đồng chí"

    def compute_cer(ref: str, hyp: str) -> float:
        import jiwer

        return float(jiwer.cer(ref, hyp))

    results: dict[str, Any] = {}
    methods = {
        "F0_FIXED": fuse_f0_fixed(hypotheses, "src_a")[0],
        "F1_BEST_SEGMENT": fuse_f1_best_segment(hypotheses)[0],
        "F3_ROVER": fuse_f3_rover(bins)[0],
        "F4_ASR_WEIGHTED": fuse_f4_asr_weighted(bins)[0],
        "F5_RULE_WEIGHTED": fuse_f5_rule_weighted(bins)[0],
        "F5_RULE_WEIGHTED_CORRECTED": fuse_f5_rule_weighted_corrected(
            bins, source_hypotheses=hypotheses
        )[0],
    }

    for name, pred in methods.items():
        results[name] = {
            "prediction": pred,
            "cer": round(compute_cer(ground_truth, pred), 4),
            "hallucination_filtered": ("ảo giác" not in pred),
        }

    return results


def run_full_ablation_benchmarks() -> dict[str, Any]:
    """Execute ablation matrix (A0 - A7) and generate summary report."""
    reports_dir = Path("reports/ablation_benchmark")
    reports_dir.mkdir(parents=True, exist_ok=True)

    sr = 16000
    dur_sec = 10.0
    time_axis = np.arange(int(sr * dur_sec), dtype=np.float32) / sr
    mic1 = (0.2 * np.sin(2 * np.pi * 220 * time_axis)).astype(np.float32)
    mic2 = (0.15 * np.sin(2 * np.pi * 220 * time_axis + 0.1)).astype(np.float32)
    synthetic_sources = {"mic1": mic1, "mic2": mic2}

    logger.info("Running Step 1: VAD Option B vs Legacy")
    vad_res = benchmark_shared_segmentation_vs_legacy(
        synthetic_sources, sr, reports_dir / "vad_bench"
    )

    logger.info("Running Step 2: Global Speaker Clustering stability")
    spk_res = benchmark_speaker_clustering_stability()

    logger.info("Running Step 3: ASR Adaptive Routing efficiency")
    asr_res = benchmark_asr_routing_efficiency()

    logger.info("Running Step 4: Transcript Fusion CER & Hallucination Filter")
    fusion_res = benchmark_fusion_methods_cer_proxy()

    ablation_matrix = [
        {
            "id": "A0",
            "name": "Baseline Khóa",
            "vad_mode": "Option A (độc lập)",
            "speaker_id_mode": "Single-turn MFCC",
            "asr_mode": "All-source ASR",
            "fusion_mode": "F0 Fixed",
            "rtf_relative": 1.0,
            "speaker_stability": "Kém (lệch track giữa các lượt)",
            "hallucination_protection": "Không có",
        },
        {
            "id": "A1",
            "name": "VAD B Chung Pyannote",
            "vad_mode": "Option B (chung 1 lần/nguồn)",
            "speaker_id_mode": "Single-turn MFCC",
            "asr_mode": "All-source ASR",
            "fusion_mode": "F0 Fixed",
            "rtf_relative": 0.72,
            "speaker_stability": "Kém (chưa có global clustering)",
            "hallucination_protection": "Không có",
        },
        {
            "id": "A2",
            "name": "Global Clustering + Unknown IDs",
            "vad_mode": "Option B",
            "speaker_id_mode": "Global Clustering (ECAPA, 2-pass)",
            "asr_mode": "All-source ASR",
            "fusion_mode": "F0 Fixed",
            "rtf_relative": 0.69,
            "speaker_stability": "Tốt (Người lạ 1/2 ổn định toàn họp)",
            "hallucination_protection": "Không có",
        },
        {
            "id": "A3",
            "name": "Source Selection & Fusion cho SID",
            "vad_mode": "Option B",
            "speaker_id_mode": "Global Clustering + P1/P3 Fusion",
            "asr_mode": "All-source ASR",
            "fusion_mode": "F0 Fixed",
            "rtf_relative": 0.68,
            "speaker_stability": "Rất tốt (chống nhiễu máy phụ)",
            "hallucination_protection": "Không có",
        },
        {
            "id": "A4",
            "name": "ASR Safe Chunks (All-source)",
            "vad_mode": "Option B",
            "speaker_id_mode": "Global Clustering + P3 Fusion",
            "asr_mode": "Safe Merge Chunks (All-source)",
            "fusion_mode": "F5 Rule Weighted",
            "rtf_relative": 0.55,
            "speaker_stability": "Rất tốt",
            "hallucination_protection": "Một phần (chưa có margin safeguard)",
        },
        {
            "id": "A5",
            "name": "ASR Adaptive Routing",
            "vad_mode": "Option B",
            "speaker_id_mode": "Global Clustering + P3 Fusion",
            "asr_mode": "Safe Chunks + Adaptive Routing",
            "fusion_mode": "F5 Rule Weighted",
            "rtf_relative": 0.38,
            "speaker_stability": "Rất tốt",
            "hallucination_protection": "Một phần (giảm ASR máy nhiễu)",
        },
        {
            "id": "A6",
            "name": "F5 Sửa (Hallucination Safeguard)",
            "vad_mode": "Option B",
            "speaker_id_mode": "Global Clustering + P3 Fusion",
            "asr_mode": "Safe Chunks + Adaptive Routing",
            "fusion_mode": "F5 Sửa (Protected)",
            "rtf_relative": 0.38,
            "speaker_stability": "Rất tốt",
            "hallucination_protection": "Bảo vệ nguồn chính (CER tối ưu)",
        },
        {
            "id": "A7",
            "name": "Toàn hệ thống (Default)",
            "vad_mode": "Option B (chung 1 lần/nguồn)",
            "speaker_id_mode": "Global Clustering + P3 Fusion",
            "asr_mode": "Adaptive Routing + Safe Context Merge",
            "fusion_mode": "F5 Sửa + Provenance Traceability",
            "rtf_relative": 0.36,
            "speaker_stability": "Xuất sắc (ms-0001/0002 + rename)",
            "hallucination_protection": "Xuất sắc (CER thấp nhất, 0 ảo giác)",
        },
    ]

    # These A0-A7 rows are a fixture inventory, not measured comparisons. The
    # previous fixed RTF and qualitative ratings were mistakenly presented as results.
    for row in ablation_matrix:
        row["rtf_relative"] = None
        row["speaker_stability"] = "Chưa đo trên audio thật"
        row["hallucination_protection"] = "Chưa đo trên audio thật"
        if row["id"] in {"A3", "A4", "A5", "A6", "A7"}:
            row["speaker_id_mode"] = "Mock fixture; không đo P3"
    ablation_matrix[-1]["name"] = "Fixture đầy đủ (không phải runtime default)"

    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "evidence_type": "mock_fixture_not_quality_or_speed_evidence",
        "runtime_speaker_policy": "P2_EMBEDDING_FUSION",
        "ablation_matrix": ablation_matrix,
        "shared_segmentation_benchmark": vad_res,
        "speaker_clustering_benchmark": spk_res,
        "asr_routing_benchmark": asr_res,
        "fusion_benchmark": fusion_res,
    }

    # Save JSON summary
    json_path = reports_dir / "ablation_summary.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # Generate Markdown Report
    md_lines = [
        "# Kiểm tra logic bằng fixture mock (không phải báo cáo chất lượng hoặc tốc độ)",
        "",
        "**Cảnh báo:** ASR/encoder dùng mock và các hàng A0-A7 không chạy trên cùng audio thật. "
        "Không dùng báo cáo này để kết luận P3, RTF hay độ chính xác. Runtime hiện mặc định P2.",
        "",
        f"**Thời gian thực hiện:** {report['timestamp']}",
        "**Mục tiêu:** Kiểm tra logic trên fixture mock; không xếp hạng cấu hình runtime.",
        "",
        "## 1. Ma trận Ablation (A0 - A7)",
        "",
        (
            "| ID | Cấu hình | VAD / Turn | Nhận diện giọng nói | ASR Routing | "
            "Dung hợp Transcript | RTF Tương đối | Ổn định Danh tính | Chống ảo giác |"
        ),
        "|---|---|---|---|---|---|---:|---|---|",
    ]
    for row in ablation_matrix:
        line_part1 = (
            f"| `{row['id']}` | **{row['name']}** | {row['vad_mode']} | "
            f"{row['speaker_id_mode']} | {row['asr_mode']} | "
        )
        line_part2 = (
            f"{row['fusion_mode']} | Chưa đo | "
            f"{row['speaker_stability']} | {row['hallucination_protection']} |"
        )
        md_lines.append(line_part1 + line_part2)

    zero_enr_str = "Đạt" if spk_res["zero_enrollment_handled"] else "Không"

    md_lines.extend(
        [
            "",
            "## 2. Kiểm tra từng tầng bằng fixture mock",
            "",
            "### 2.1. Tầng VAD & Phân đoạn (Option B vs Legacy)",
            f"- **Thời gian chạy Option B:** `{vad_res['shared_vad_time_sec']}s`",
            f"- **Thời gian ước tính theo Legacy:** `{vad_res['legacy_vad_time_sec']}s`",
            "- **Tỉ lệ tăng tốc runtime:** Chưa đo (legacy ở đây chỉ nhân đôi thời gian mock).",
            (
                f"- **Vùng VAD phát hiện:** `{vad_res['vad_regions_found']}`, "
                f"**Speaker turns:** `{vad_res['speaker_turns_found']}`"
            ),
            "",
            "### 2.2. Tầng Nhận diện Danh tính & Gom cụm Toàn cục (Global Speaker Clustering)",
            f"- **Hỗ trợ 0 hồ sơ đăng ký:** `{zero_enr_str}`",
            (
                f"- **Chuỗi nhãn trên fixture mock:** "
                f"`{'không đổi' if spk_res['is_stable'] else 'thay đổi'}`"
            ),
            (
                f"- **Nhãn Người lạ A:** `{spk_res['speaker_a_stable_label']}`, "
                f"**Nhãn Người lạ B:** `{spk_res['speaker_b_stable_label']}`"
            ),
            f"- **Mã định danh họp bền vững:** `{spk_res['meeting_speaker_ids']}`",
            "",
            "### 2.3. Tầng ASR Chunking & Adaptive Routing",
            f"- **Tổng số nguồn trong đoạn:** `{asr_res['total_sources']}`",
            (
                f"- **Số nguồn được chọn ASR (chất lượng cao):** "
                f"`{asr_res['calls_adaptive']}` ({asr_res['transcribed_sources']})"
            ),
            (
                f"- **Số nguồn bị loại bỏ trước ASR:** "
                f"`{asr_res['saved_calls']}` ({asr_res['abstained_sources']})"
            ),
            f"- **Giảm lượt gọi mock ASR trên fixture:** {asr_res['reduction_percentage']}",
            "",
            "### 2.4. Tầng Dung hợp Transcript (Baselines vs F5 Sửa)",
            "| Phương pháp | Transcript đầu ra | CER Proxy | Lọc được từ ảo giác? |",
            "|---|---|---:|---|",
        ]
    )
    for m_name, m_data in fusion_res.items():
        md_lines.append(
            f"| `{m_name}` | {m_data['prediction']} | **{m_data['cer'] * 100:.2f}%** | "
            f"{'✅ Đã lọc' if m_data['hallucination_filtered'] else '❌ Bị lọt ảo giác'} |"
        )

    md_lines.extend(
        [
            "",
            "## 3. Giới hạn",
            "- Các phép đo speaker-only bằng encoder thật được thực hiện riêng trong "
            "`scripts/evaluate_speaker_multisource.py`.",
            "- Không có kết luận chất lượng hoặc tốc độ end-to-end từ fixture này.",
        ]
    )

    md_path = reports_dir / "ablation_summary.md"
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    logger.info(f"Ablation benchmark finished. Report saved to {md_path}")

    return report


if __name__ == "__main__":
    run_full_ablation_benchmarks()
