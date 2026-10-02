"""Timing and hardware resource profiling utilities for CPU benchmark."""

from __future__ import annotations

import gc
import platform
import time
from typing import Any

import numpy as np

from experiments.speaker_identification.classifiers.base import BaseClassifier
from experiments.speaker_identification.contracts import SpeakerEncoder


def get_hardware_environment() -> dict[str, Any]:
    """Capture environment hardware and library version information."""
    import torch

    return {
        "os": platform.system(),
        "os_release": platform.release(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "torch_version": torch.__version__,
        "num_cpu_threads": torch.get_num_threads(),
        "device": "cpu",
    }


def measure_cold_load_time(loader_fn: Any) -> float:
    """Measure cold model load time in seconds."""
    gc.collect()
    start = time.perf_counter()
    loader_fn()
    return float(time.perf_counter() - start)


def benchmark_encoder_timing(
    encoder: SpeakerEncoder,
    waveforms: list[np.ndarray],
    num_warmup: int = 5,
    num_repeats: int = 20,
) -> dict[str, float]:
    """Benchmark warm feature extraction latency on CPU without caching."""
    if not waveforms:
        raise ValueError("waveforms cannot be empty")

    # Warmup
    for i in range(min(num_warmup, len(waveforms))):
        encoder.encode(waveforms[i])

    durations: list[float] = []
    latencies: list[float] = []

    for i in range(min(num_repeats, len(waveforms))):
        w = waveforms[i]
        audio_dur = len(w) / encoder.sample_rate
        durations.append(audio_dur)

        start = time.perf_counter()
        encoder.encode(w)
        latency_sec = time.perf_counter() - start
        latencies.append(latency_sec * 1000.0)  # ms

    arr = np.asarray(latencies, dtype=np.float64)
    tot_proc_sec = float(np.sum(arr) / 1000.0)
    tot_audio_sec = float(np.sum(durations))
    rtf = tot_proc_sec / max(tot_audio_sec, 1e-6)

    return {
        "mean_ms": float(np.mean(arr)),
        "median_ms": float(np.median(arr)),
        "p95_ms": float(np.percentile(arr, 95)),
        "std_ms": float(np.std(arr)),
        "rtf": rtf,
    }


def benchmark_end_to_end_timing(
    encoder: SpeakerEncoder,
    classifier: BaseClassifier,
    support_waveforms: dict[str, list[np.ndarray]],
    query_waveforms: list[np.ndarray],
    num_warmup: int = 5,
) -> dict[str, float]:
    """Measure end-to-end enrollment, classifier-only and pipeline latency."""
    # Measure enrollment
    enroll_start = time.perf_counter()
    support_embs: dict[str, list[np.ndarray]] = {}
    for spk, waves in support_waveforms.items():
        support_embs[spk] = [encoder.encode(w) for w in waves]
    fit_start = time.perf_counter()
    classifier.fit(support_embs)
    fit_time_ms = (time.perf_counter() - fit_start) * 1000.0
    total_enroll_ms = (time.perf_counter() - enroll_start) * 1000.0
    enroll_per_speaker_ms = total_enroll_ms / max(len(support_waveforms), 1)

    # Warmup query
    for i in range(min(num_warmup, len(query_waveforms))):
        emb = encoder.encode(query_waveforms[i])
        classifier.predict(emb, is_open_set=True)

    e2e_latencies: list[float] = []
    clf_latencies: list[float] = []
    query_durations: list[float] = []

    for w in query_waveforms:
        q_dur = len(w) / encoder.sample_rate
        query_durations.append(q_dur)

        t0 = time.perf_counter()
        emb = encoder.encode(w)
        t1 = time.perf_counter()
        classifier.predict(emb, is_open_set=True)
        t2 = time.perf_counter()

        e2e_latencies.append((t2 - t0) * 1000.0)
        clf_latencies.append((t2 - t1) * 1000.0)

    e2e_arr = np.asarray(e2e_latencies, dtype=np.float64)
    clf_arr = np.asarray(clf_latencies, dtype=np.float64)
    tot_proc_sec = float(np.sum(e2e_arr) / 1000.0)
    tot_audio_sec = float(np.sum(query_durations))
    rtf = tot_proc_sec / max(tot_audio_sec, 1e-6)

    return {
        "enrollment_per_speaker_ms": float(enroll_per_speaker_ms),
        "fit_time_ms": float(fit_time_ms),
        "classifier_only_mean_ms": float(np.mean(clf_arr)),
        "classifier_only_p95_ms": float(np.percentile(clf_arr, 95)),
        "e2e_mean_ms": float(np.mean(e2e_arr)),
        "e2e_median_ms": float(np.median(e2e_arr)),
        "e2e_p95_ms": float(np.percentile(e2e_arr, 95)),
        "e2e_std_ms": float(np.std(e2e_arr)),
        "rtf": rtf,
    }
