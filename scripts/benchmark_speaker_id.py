"""Benchmark script comparing ECAPA-TDNN vs MFCC+KNN on the VIVOS Vietnamese speech dataset."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from meeting_pipeline.application.speakers import SpeakerProfileInput, SpeakerRegistry
from meeting_pipeline.config import load_config
from meeting_pipeline.domain.speaker_classifier import (
    ECAPASpeakerClassifier,
    MFCCKNNSpeakerClassifier,
)


def load_audio_mono_16k(path: Path) -> np.ndarray:
    wave, sr = sf.read(path, dtype="float32")
    if wave.ndim > 1:
        wave = wave.mean(axis=1)
    if sr != 16000:
        import librosa

        wave = librosa.resample(wave, orig_sr=sr, target_sr=16000)
    return wave.astype(np.float32)


def run_benchmark() -> dict[str, Any]:
    print("=" * 70)
    print(" BẮT ĐẦU BENCHMARK: ECAPA-TDNN vs MFCC+KNN TRÊN TẬP DỮ LIỆU VIVOS")
    print("=" * 70)

    config = load_config(Path("configs/default.yaml"))
    speaker_registry = SpeakerRegistry(config)

    vivos_test_dir = Path("data/external/vivos/extracted/vivos/test/waves")
    if not vivos_test_dir.is_dir():
        raise FileNotFoundError(f"Không tìm thấy thư mục VIVOS test: {vivos_test_dir}")

    all_speaker_dirs = sorted([p for p in vivos_test_dir.iterdir() if p.is_dir()])
    print(f"Tổng số người nói có sẵn trong VIVOS test: {len(all_speaker_dirs)}")

    # -------------------------------------------------------------------------
    # EXPERIMENT 1: CLOSED-SET SPEAKER IDENTIFICATION (8 Người - Chuẩn Phòng Họp)
    # -------------------------------------------------------------------------
    print("\n" + "-" * 70)
    print("THỰC NGHIỆM 1: Phân Loại Đóng (Closed-set) với 8 Người Nói (8 Speakers)")
    print("  - Mỗi người: 2 mẫu âm thanh dùng để Đăng ký (Enrollment)")
    print("  - Mỗi người: 20 mẫu âm thanh dùng để Đánh giá (Evaluation)")
    print("  - Tổng số mẫu kiểm tra: 8 x 20 = 160 mẫu")
    print("-" * 70)

    num_closed_speakers = min(8, len(all_speaker_dirs))
    closed_speakers = all_speaker_dirs[:num_closed_speakers]

    profiles: list[SpeakerProfileInput] = []
    eval_dataset: list[tuple[str, np.ndarray, Path]] = []  # (true_speaker_id, wave, path)

    print("Đang chuẩn bị hồ sơ đăng ký và tập đánh giá...")
    for spk_dir in closed_speakers:
        spk_id = spk_dir.name
        wav_files = sorted(spk_dir.glob("*.wav"))
        if len(wav_files) < 22:
            raise ValueError(f"Người nói {spk_id} không đủ 22 file (chỉ có {len(wav_files)})")

        enroll_files = wav_files[:2]
        test_files = wav_files[2:22]

        # Load enroll waveforms
        enroll_waves = [load_audio_mono_16k(f) for f in enroll_files]

        # Compute ECAPA prototype
        ecapa_embeddings = [speaker_registry.encode(w) for w in enroll_waves]
        prototype = np.mean(np.stack(ecapa_embeddings), axis=0)
        prototype /= max(float(np.linalg.norm(prototype)), 1e-12)

        profiles.append(
            SpeakerProfileInput(
                speaker_id=spk_id,
                display_name=f"Speaker {spk_id}",
                embedding=prototype.astype(np.float32),
                sample_waveforms=tuple(enroll_waves),
            )
        )

        for tf in test_files:
            eval_dataset.append((spk_id, load_audio_mono_16k(tf), tf))

    print(f"Đã tạo {len(profiles)} hồ sơ đăng ký.")
    print(f"Tổng số mẫu test sẵn sàng: {len(eval_dataset)}")

    # Khởi tạo 2 bộ phân lớp
    ecapa_clf = ECAPASpeakerClassifier(
        encoder=speaker_registry,
        profiles=profiles,
        identity_threshold=0.25,
        identity_margin=0.05,
    )

    knn_clf = MFCCKNNSpeakerClassifier(
        profiles=profiles,
        n_neighbors=5,
        metric="cosine",
        identity_threshold=0.25,
        identity_margin=0.05,
        window_sec=1.5,
        step_sec=0.5,
    )

    # Đánh giá ECAPA-TDNN trên Closed-set
    print("\nĐang chạy đánh giá ECAPA-TDNN...")
    ecapa_correct = 0
    ecapa_times: list[float] = []
    for true_spk, wave, _ in eval_dataset:
        t0 = time.perf_counter()
        res = ecapa_clf.assign_speaker(wave, excluded=set())
        t1 = time.perf_counter()
        ecapa_times.append((t1 - t0) * 1000.0)  # ms
        if res.get("profile_id") == true_spk:
            ecapa_correct += 1

    ecapa_acc = (ecapa_correct / len(eval_dataset)) * 100.0
    ecapa_avg_time = float(np.mean(ecapa_times))
    ecapa_med_time = float(np.median(ecapa_times))

    # Đánh giá MFCC + KNN trên Closed-set
    print("Đang chạy đánh giá MFCC + KNN...")
    knn_correct = 0
    knn_times: list[float] = []
    for true_spk, wave, _ in eval_dataset:
        t0 = time.perf_counter()
        res = knn_clf.assign_speaker(wave, excluded=set())
        t1 = time.perf_counter()
        knn_times.append((t1 - t0) * 1000.0)  # ms
        if res.get("profile_id") == true_spk:
            knn_correct += 1

    knn_acc = (knn_correct / len(eval_dataset)) * 100.0
    knn_avg_time = float(np.mean(knn_times))
    knn_med_time = float(np.median(knn_times))

    print("\nKẾT QUẢ THỰC NGHIỆM 1 (CLOSED-SET - 8 NGƯỜI):")
    print(
        f"  + ECAPA-TDNN: Độ chính xác Top-1 = {ecapa_acc:.2f}% "
        f"({ecapa_correct}/{len(eval_dataset)}) | Thời gian TB = {ecapa_avg_time:.2f} ms/mẫu"
    )
    print(
        f"  + MFCC + KNN: Độ chính xác Top-1 = {knn_acc:.2f}% "
        f"({knn_correct}/{len(eval_dataset)}) | Thời gian TB = {knn_avg_time:.2f} ms/mẫu"
    )

    # -------------------------------------------------------------------------
    # EXPERIMENT 2: OPEN-SET SPEAKER IDENTIFICATION (5 Đã Đăng Ký + 5 Người Lạ)
    # -------------------------------------------------------------------------
    print("\n" + "-" * 70)
    print("THỰC NGHIỆM 2: Phân Loại Mở (Open-set) - Nhận Diện Người Quen & Từ Chối Người Lạ")
    print("  - 5 Người ĐÃ ĐĂNG KÝ (Known): 5 x 15 = 75 mẫu kiểm tra")
    print("  - 5 Người CHƯA ĐĂNG KÝ / Người Lạ (Unknown): 5 x 15 = 75 mẫu kiểm tra")
    print("  - Tổng số mẫu kiểm tra: 150 mẫu")
    print("-" * 70)

    known_spks = all_speaker_dirs[:5]
    unknown_spks = all_speaker_dirs[5:10]

    open_profiles: list[SpeakerProfileInput] = []
    known_eval: list[tuple[str, np.ndarray]] = []
    unknown_eval: list[tuple[str, np.ndarray]] = []

    for spk_dir in known_spks:
        spk_id = spk_dir.name
        wavs = sorted(spk_dir.glob("*.wav"))
        enroll_waves = [load_audio_mono_16k(f) for f in wavs[:2]]
        ecapa_embs = [speaker_registry.encode(w) for w in enroll_waves]
        proto = np.mean(np.stack(ecapa_embs), axis=0)
        proto /= max(float(np.linalg.norm(proto)), 1e-12)

        open_profiles.append(
            SpeakerProfileInput(
                speaker_id=spk_id,
                display_name=f"Speaker {spk_id}",
                embedding=proto.astype(np.float32),
                sample_waveforms=tuple(enroll_waves),
            )
        )
        for tf in wavs[2:17]:
            known_eval.append((spk_id, load_audio_mono_16k(tf)))

    for spk_dir in unknown_spks:
        spk_id = spk_dir.name
        wavs = sorted(spk_dir.glob("*.wav"))
        for tf in wavs[:15]:
            unknown_eval.append((spk_id, load_audio_mono_16k(tf)))

    print(f"Số người đã đăng ký: {len(open_profiles)} (75 mẫu)")
    print(f"Số người lạ thử nghiệm: {len(unknown_spks)} (75 mẫu)")

    open_ecapa = ECAPASpeakerClassifier(
        encoder=speaker_registry,
        profiles=open_profiles,
        identity_threshold=0.25,
        identity_margin=0.05,
    )

    open_knn = MFCCKNNSpeakerClassifier(
        profiles=open_profiles,
        n_neighbors=5,
        metric="cosine",
        identity_threshold=0.25,
        identity_margin=0.05,
    )

    # Đánh giá ECAPA Open-set
    ecapa_tp = sum(
        1
        for true_spk, w in known_eval
        if open_ecapa.assign_speaker(w, set()).get("profile_id") == true_spk
    )
    ecapa_tn = sum(
        1
        for _, w in unknown_eval
        if open_ecapa.assign_speaker(w, set()).get("speaker_status") == "unknown"
    )
    ecapa_known_acc = (ecapa_tp / len(known_eval)) * 100.0
    ecapa_unk_rej = (ecapa_tn / len(unknown_eval)) * 100.0
    ecapa_bal_acc = (ecapa_known_acc + ecapa_unk_rej) / 2.0

    # Đánh giá KNN Open-set
    knn_tp = sum(
        1
        for true_spk, w in known_eval
        if open_knn.assign_speaker(w, set()).get("profile_id") == true_spk
    )
    knn_tn = sum(
        1
        for _, w in unknown_eval
        if open_knn.assign_speaker(w, set()).get("speaker_status") == "unknown"
    )
    knn_known_acc = (knn_tp / len(known_eval)) * 100.0
    knn_unk_rej = (knn_tn / len(unknown_eval)) * 100.0
    knn_bal_acc = (knn_known_acc + knn_unk_rej) / 2.0

    print("\nKẾT QUẢ THỰC NGHIỆM 2 (OPEN-SET - 5 NGƯỜI QUEN + 5 NGƯỜI LẠ):")
    print("  + ECAPA-TDNN:")
    print(
        f"      - Nhận đúng người quen (TPR): {ecapa_known_acc:.2f}% ({ecapa_tp}/{len(known_eval)})"
    )
    print(
        f"      - Từ chối đúng người lạ (TNR): {ecapa_unk_rej:.2f}% "
        f"({ecapa_tn}/{len(unknown_eval)})"
    )
    print(f"      - Độ chính xác cân bằng (Balanced Acc): {ecapa_bal_acc:.2f}%")
    print("  + MFCC + KNN:")
    print(f"      - Nhận đúng người quen (TPR): {knn_known_acc:.2f}% ({knn_tp}/{len(known_eval)})")
    print(f"      - Từ chối đúng người lạ (TNR): {knn_unk_rej:.2f}% ({knn_tn}/{len(unknown_eval)})")
    print(f"      - Độ chính xác cân bằng (Balanced Acc): {knn_bal_acc:.2f}%")

    report = {
        "closed_set": {
            "num_speakers": num_closed_speakers,
            "num_eval_samples": len(eval_dataset),
            "ecapa": {
                "accuracy": ecapa_acc,
                "correct": ecapa_correct,
                "avg_latency_ms": ecapa_avg_time,
                "median_latency_ms": ecapa_med_time,
            },
            "mfcc_knn": {
                "accuracy": knn_acc,
                "correct": knn_correct,
                "avg_latency_ms": knn_avg_time,
                "median_latency_ms": knn_med_time,
            },
        },
        "open_set": {
            "num_known_speakers": len(known_spks),
            "num_unknown_speakers": len(unknown_spks),
            "ecapa": {
                "known_accuracy": ecapa_known_acc,
                "unknown_rejection_rate": ecapa_unk_rej,
                "balanced_accuracy": ecapa_bal_acc,
            },
            "mfcc_knn": {
                "known_accuracy": knn_known_acc,
                "unknown_rejection_rate": knn_unk_rej,
                "balanced_accuracy": knn_bal_acc,
            },
        },
    }

    report_path = Path("docs/speaker_id_benchmark_vivos.json")
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nĐã lưu kết quả chi tiết vào: {report_path}")
    print("=" * 70)
    return report


if __name__ == "__main__":
    run_benchmark()
