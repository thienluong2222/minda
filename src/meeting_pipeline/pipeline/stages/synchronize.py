"""Signal-based source alignment with explicit coverage."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import signal

from meeting_pipeline.domain.errors import AlignmentError
from meeting_pipeline.domain.time_mapping import AffineTimeMapping


@dataclass(frozen=True, slots=True)
class AlignmentEstimate:
    """Offset-only mapping and evidence produced by coarse envelope correlation."""

    mapping: AffineTimeMapping
    peak_ratio: float
    residual_sec: float
    status: str


def log_energy_envelope(
    samples: np.ndarray, sample_rate: int, envelope_rate_hz: int = 100
) -> np.ndarray:
    """Return a robust log-energy envelope from mono float samples.

    The result uses an envelope clock starting at source sample zero. Frames do not
    overlap so offsets remain interpretable at ``1 / envelope_rate_hz`` seconds.
    """
    if samples.ndim != 1 or sample_rate <= 0 or envelope_rate_hz <= 0:
        raise ValueError("Expected mono samples and positive rates")
    frame = max(1, round(sample_rate / envelope_rate_hz))
    usable = samples.size - samples.size % frame
    if usable == 0:
        raise AlignmentError("Audio is too short to form an energy envelope")
    framed = samples[:usable].reshape(-1, frame).astype(np.float64, copy=False)
    energy = np.mean(np.square(framed), axis=1)
    envelope = np.log1p(1000.0 * energy)
    return np.asarray(envelope - np.median(envelope), dtype=np.float64)


def estimate_offset(
    reference: np.ndarray,
    source: np.ndarray,
    sample_rate: int,
    envelope_rate_hz: int = 100,
    max_offset_seconds: float = 120,
) -> AlignmentEstimate:
    """Estimate ``t = u + b`` from mono signals on equal sample-rate clocks.

    A positive returned offset means the source begins later on the meeting clock.
    Silence-only and ambiguous correlations are rejected instead of force-aligned.
    """
    reference_envelope = log_energy_envelope(reference, sample_rate, envelope_rate_hz)
    source_envelope = log_energy_envelope(source, sample_rate, envelope_rate_hz)
    if np.std(reference_envelope) < 1e-5 or np.std(source_envelope) < 1e-5:
        raise AlignmentError("Alignment requires non-silent, varying evidence")
    correlation = signal.correlate(
        source_envelope / np.linalg.norm(source_envelope),
        reference_envelope / np.linalg.norm(reference_envelope),
        mode="full",
        method="fft",
    )
    lags = signal.correlation_lags(source_envelope.size, reference_envelope.size, mode="full")
    limit = round(max_offset_seconds * envelope_rate_hz)
    valid = np.abs(lags) <= limit
    values = correlation[valid]
    valid_lags = lags[valid]
    if values.size < 2:
        raise AlignmentError("No lag candidates lie within max_offset_seconds")
    peak_index = int(np.argmax(values))
    peak = float(values[peak_index])
    guard = max(1, round(0.05 * envelope_rate_hz))
    competitors = values.copy()
    competitors[max(0, peak_index - guard) : peak_index + guard + 1] = 0
    second_peak = float(np.max(competitors, initial=0))
    peak_ratio = peak / max(second_peak, 1e-12)
    if peak < 0.1 or peak_ratio < 1.05:
        raise AlignmentError("Correlation peak is ambiguous")
    # For correlate(source, reference), lag is the shift applied to source time in
    # the contract t = u + b. A source whose matching event occurs later needs b < 0.
    offset_sec = float(-valid_lags[peak_index] / envelope_rate_hz)
    return AlignmentEstimate(
        mapping=AffineTimeMapping(scale=1.0, offset_sec=offset_sec),
        peak_ratio=peak_ratio,
        residual_sec=0.5 / envelope_rate_hz,
        status="drift_unresolved",
    )


def union_coverage(
    mappings_and_durations: list[tuple[AffineTimeMapping, float]],
) -> tuple[float, list[tuple[float, float]]]:
    """Shift meeting origin to zero and return each source's half-open coverage."""
    if not mappings_and_durations:
        raise ValueError("At least one source is required")
    starts = [mapping.source_to_meeting(0) for mapping, _ in mappings_and_durations]
    origin_shift = -min(starts)
    coverage = [
        (
            mapping.source_to_meeting(0) + origin_shift,
            mapping.source_to_meeting(duration) + origin_shift,
        )
        for mapping, duration in mappings_and_durations
    ]
    return origin_shift, coverage
