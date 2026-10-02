"""3D Acoustic room simulation using pyroomacoustics.

Specification: Section 7 of docs/PLAN_VIVOS_SYNTHETIC_PIPELINE.md.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pyroomacoustics as pra

logger = logging.getLogger(__name__)


def compute_room_rirs(
    dimensions: list[float],
    rt60: float,
    speaker_positions: dict[str, list[float]],
    device_positions: dict[str, list[float]],
    sample_rate: int = 16000,
    max_order: int = 8,
) -> dict[str, dict[str, np.ndarray[Any, np.dtype[np.float32]]]]:
    """Compute Room Impulse Responses (RIR) for all (speaker, device) pairs.

    Returns:
        Mapping: speaker_id -> device_id -> 1D float32 numpy array representing RIR.
    """
    # Estimate absorption from desired RT60 using Sabine's formula
    try:
        e_absorption, computed_order = pra.inverse_sabine(rt60, dimensions)
        order = min(max(computed_order, 3), max_order)
    except Exception as exc:
        logger.warning("inverse_sabine calculation failed: %s; falling back to default 0.2", exc)
        e_absorption = 0.25
        order = max_order

    material = pra.Material(e_absorption)
    room = pra.ShoeBox(
        dimensions,
        fs=sample_rate,
        materials=material,
        max_order=order,
        ray_tracing=False,
    )

    # Sort keys for deterministic mic and source indices
    sorted_speakers = sorted(speaker_positions.keys())
    sorted_devices = sorted(device_positions.keys())

    # Add microphones (devices)
    dev_locs = [device_positions[d] for d in sorted_devices]
    mic_array_locs = np.array(dev_locs).T  # shape (3, num_mics)
    room.add_microphone_array(pra.MicrophoneArray(mic_array_locs, fs=sample_rate))

    # Add sources (speakers)
    for spk_id in sorted_speakers:
        room.add_source(speaker_positions[spk_id])

    # Compute RIRs
    room.compute_rir()

    rirs: dict[str, dict[str, np.ndarray[Any, np.dtype[np.float32]]]] = {}
    for spk_idx, spk_id in enumerate(sorted_speakers):
        rirs[spk_id] = {}
        for dev_idx, dev_id in enumerate(sorted_devices):
            rir_raw = room.rir[dev_idx][spk_idx]
            # Convert to float32 numpy array and normalize if needed
            rir_arr = np.asarray(rir_raw, dtype=np.float32)
            rirs[spk_id][dev_id] = rir_arr

    return rirs


def compute_direct_path_energy(
    rir: np.ndarray[Any, np.dtype[np.float32]],
    window_samples: int = 80,
) -> float:
    """Compute energy in the direct path (first arrival peak window)."""
    if len(rir) == 0:
        return 0.0
    peak_idx = int(np.argmax(np.abs(rir)))
    start_idx = max(0, peak_idx - 10)
    end_idx = min(len(rir), peak_idx + window_samples)
    direct_slice = rir[start_idx:end_idx]
    return float(np.sum(direct_slice**2))
