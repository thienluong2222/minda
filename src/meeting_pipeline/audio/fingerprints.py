"""Conservative landmark alignment for recordings of the same acoustic event.

Spectral peak pairs find candidates; local waveform correlation refines them.
This is a small, testable implementation inspired by Six & Leman (2015), not a
reimplementation of their benchmark or Tsai's adaptive eigenfilters.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations, pairwise
from typing import Any

import numpy as np
from scipy import ndimage, signal

Array = np.ndarray[Any, Any]


@dataclass
class Fingerprint:
    hashes: Array
    times: Array
    duration: float


@dataclass
class AcousticMap:
    start: float
    end: float
    scale: float
    offset: float
    residual_ms: float
    anchors: int
    fine_validated: bool = False
    boundary_uncertainty_ms: float | None = None

    def inverse(self) -> AcousticMap:
        return AcousticMap(
            self.start * self.scale + self.offset,
            self.end * self.scale + self.offset,
            1 / self.scale,
            -self.offset / self.scale,
            self.residual_ms,
            self.anchors,
            self.fine_validated,
            self.boundary_uncertainty_ms,
        )


def fingerprint(samples: Array, sample_rate: int) -> Fingerprint:
    duration = len(samples) / sample_rate
    if sample_rate != 8000:
        divisor = int(np.gcd(sample_rate, 8000))
        samples = signal.resample_poly(samples, 8000 // divisor, sample_rate // divisor)
    # Process STFT blocks, retaining only sparse landmarks, not full spectrograms.
    peaks = []
    hop, fft = 128, 512
    block = hop * 1875  # exactly 30 seconds on the fingerprint frame clock
    for start in range(0, len(samples), block):
        chunk = samples[start : min(len(samples), start + block + fft)]
        if len(chunk) < fft:
            break
        _, times, transform = signal.stft(
            chunk,
            8000,
            nperseg=fft,
            noverlap=fft - hop,
            boundary=None,
            padded=False,
        )
        magnitude = np.abs(transform)
        if np.max(magnitude, initial=0) < 1e-7:
            continue
        local = ndimage.maximum_filter(magnitude, size=(9, 7))
        mask = (magnitude == local) & (magnitude > np.percentile(magnitude, 80, axis=0))
        mask[:8] = False
        mask[230:] = False
        # Temporal nonmaximum suppression is translation invariant. Fixed cells
        # made an identical repeated passage look weaker merely because its start
        # fell on another cell boundary, hiding a genuinely ambiguous match.
        rows, columns = np.where(mask)
        priority = np.argsort(magnitude[rows, columns])[::-1]
        blocked = np.zeros(len(times), dtype=bool)
        for index in priority:
            column = int(columns[index])
            time = float(times[column] + start / 8000)
            if not blocked[column] and time < (start + block) / 8000:
                peaks.append((time, int(rows[index])))
                blocked[max(0, column - 3) : min(len(times), column + 4)] = True
    peaks.sort()
    hashes, positions = [], []
    for index, (time, frequency) in enumerate(peaks):
        fanout = 0
        for later, other in peaks[index + 1 : index + 40]:
            delta = round((later - time) * 8000 / hop)
            if delta < 3:
                continue
            if delta > 45:
                break
            hashes.append(((frequency // 2) << 20) | ((other // 2) << 10) | (delta // 2))
            positions.append(time)
            fanout += 1
            if fanout == 4:
                break
    return Fingerprint(
        np.asarray(hashes, dtype=np.int64), np.asarray(positions, dtype=np.float64), duration
    )


def candidate_pairs(
    features: dict[str, Fingerprint], maximum_neighbors: int = 4
) -> list[tuple[str, str]]:
    owners = defaultdict(list)
    for clip_id, feature in features.items():
        for value in np.unique(feature.hashes):
            owners[int(value)].append(clip_id)
    votes: Counter[tuple[str, str]] = Counter()
    for clips in owners.values():
        if 2 <= len(clips) <= 16:
            for left, right in combinations(sorted(clips), 2):
                votes[(left, right)] += 1
    selected: list[tuple[str, str]] = []
    degree: Counter[str] = Counter()
    for pair, count in sorted(votes.items(), key=lambda row: (-row[1], row[0])):
        if count >= 12 and min(degree[pair[0]], degree[pair[1]]) < maximum_neighbors:
            selected.append(pair)
            degree.update(pair)
    return selected


def match_fingerprints(
    reference: Fingerprint, query: Fingerprint, minimum_common_sec: float = 3.0
) -> list[AcousticMap]:
    index: dict[int, list[float]] = defaultdict(list)
    for value, time in zip(reference.hashes, reference.times, strict=True):
        index[int(value)].append(float(time))
    index = {value: times for value, times in index.items() if len(times) <= 24}
    points: list[tuple[float, float]] = []
    window = max(6.0, minimum_common_sec * 2)
    for window_start in np.arange(0, max(0.01, query.duration - minimum_common_sec), 2.0):
        selected = np.flatnonzero(
            (query.times >= window_start) & (query.times < window_start + window)
        )
        pairs = set()
        for i in selected:
            q = float(query.times[i])
            for r in index.get(int(query.hashes[i]), []):
                pairs.add((round(q, 4), round(r, 4)))
        if len(pairs) < 12:
            continue
        candidates = np.asarray(sorted(pairs))
        offsets = candidates[:, 1] - candidates[:, 0]
        bins = np.round(offsets / 0.064).astype(np.int64)
        counts = Counter(bins)
        clustered = {
            value: counts[value - 1] + counts[value] + counts[value + 1] for value in counts
        }
        best = max(clustered, key=lambda value: clustered[value])
        keep = np.abs(bins - best) <= 1
        support = candidates[keep]
        competing = max(
            (count for value, count in clustered.items() if abs(value - best) > 3), default=0
        )
        if len(support) < max(12, competing * 1.5):
            continue
        if np.ptp(support[:, 0]) < minimum_common_sec:
            continue
        if len(np.unique(np.round(support[:, 0] * 10))) < 8:
            continue
        points.extend((float(q), float(r)) for q, r in support)
    if not points:
        return []
    # One robust anchor per half second avoids counting repeated window votes.
    buckets = defaultdict(list)
    for q, r in set(points):
        buckets[int(q * 2)].append((q, r))
    anchors = []
    for bucket in sorted(buckets):
        values = np.asarray(buckets[bucket])
        offsets = values[:, 1] - values[:, 0]
        median = float(np.median(offsets))
        keep = np.abs(offsets - median) < 0.08
        if np.count_nonzero(keep) >= 2:
            q = float(np.median(values[keep, 0]))
            anchors.append((q, q + float(np.median(offsets[keep]))))
    groups: list[list[tuple[float, float]]] = []
    for anchor in anchors:
        if (
            not groups
            or anchor[0] - groups[-1][-1][0] > 12
            or abs((anchor[1] - anchor[0]) - (groups[-1][-1][1] - groups[-1][-1][0])) > 0.18
        ):
            groups.append([])
        groups[-1].append(anchor)
    maps = []
    for group in groups:
        if len(group) < 4 or group[-1][0] - group[0][0] < minimum_common_sec:
            continue
        values = np.asarray(group)
        scale, offset = np.polyfit(values[:, 0], values[:, 1], 1)
        errors = values[:, 1] - (scale * values[:, 0] + offset)
        inliers = np.abs(errors - np.median(errors)) <= max(0.025, 3 * np.median(np.abs(errors)))
        if np.count_nonzero(inliers) < 4:
            continue
        scale, offset = np.polyfit(values[inliers, 0], values[inliers, 1], 1)
        residual = float(
            np.sqrt(np.mean((values[inliers, 1] - (scale * values[inliers, 0] + offset)) ** 2))
        )
        if abs(scale - 1) > 0.002 or residual > 0.04:
            continue
        start, end = float(values[inliers, 0].min()), float(values[inliers, 0].max())
        if start < 3:
            start = 0.0
        if query.duration - end < 3:
            end = query.duration
        maps.append(
            AcousticMap(
                start,
                end,
                float(scale),
                float(offset),
                residual * 1000,
                int(np.count_nonzero(inliers)),
            )
        )
    return maps


def refine_offset(
    reference: Array,
    query: Array,
    sample_rate: int,
    offset: float,
    query_center: float,
    window_sec: float = 2.0,
) -> float | None:
    """Refine a candidate only when waveform correlation has a unique strong peak."""
    start = max(0.0, query_center - window_sec / 2, -offset)
    size = min(
        round(window_sec * sample_rate),
        len(query) - round(start * sample_rate),
        len(reference) - round((start + offset) * sample_rate),
    )
    if size < sample_rate // 2:
        return None
    q = query[round(start * sample_rate) : round(start * sample_rate) + size].astype(np.float64)
    r = reference[
        round((start + offset) * sample_rate) : round((start + offset) * sample_rate) + size
    ].astype(np.float64)
    q -= q.mean()
    r -= r.mean()
    norm = np.linalg.norm(q) * np.linalg.norm(r)
    if norm < 1e-8:
        return None
    correlation = signal.correlate(r, q, mode="full", method="fft") / norm
    lags = signal.correlation_lags(len(r), len(q))
    keep = np.abs(lags) <= round(0.08 * sample_rate)
    values, shifts = correlation[keep], lags[keep]
    peak = int(np.argmax(values))
    competitors = values.copy()
    guard = max(1, round(0.005 * sample_rate))
    competitors[max(0, peak - guard) : peak + guard + 1] = 0
    if values[peak] < 0.2 or values[peak] < 1.2 * max(competitors.max(initial=0), 1e-8):
        return None
    return float(offset + shifts[peak] / sample_rate)


def refine_maps(
    maps: list[AcousticMap], reference: Array, query: Array, sample_rate: int
) -> list[AcousticMap]:
    """Refine offset/rate and a discontinuity only when local evidence agrees.

    If the transition cannot be localized, its unmatched bridge stays unresolved;
    it is never stretched into a fabricated smooth clock mapping.
    """
    for mapping in maps:
        points = []
        for center in np.linspace(mapping.start + 1, mapping.end - 1, 5):
            if mapping.end - mapping.start < 3:
                break
            offset = (mapping.scale - 1) * center + mapping.offset
            refined = refine_offset(reference, query, sample_rate, offset, float(center))
            if refined is not None:
                points.append((center, center + refined))
        if len(points) >= 3:
            values = np.asarray(points)
            scale, offset = np.polyfit(values[:, 0], values[:, 1], 1)
            residual = float(np.sqrt(np.mean((values[:, 1] - scale * values[:, 0] - offset) ** 2)))
            if abs(scale - 1) < 0.002 and residual < 0.02:
                mapping.scale, mapping.offset = float(scale), float(offset)
                mapping.residual_ms = residual * 1000
                mapping.fine_validated = True

    def similarity(time: float, mapping: AcousticMap) -> float:
        radius = round(0.08 * sample_rate)
        q_start = round(time * sample_rate) - radius
        r_start = round((mapping.scale * time + mapping.offset) * sample_rate) - radius
        margin = round(0.04 * sample_rate)
        if min(q_start, r_start - margin) < 0:
            return 0.0
        q = query[q_start : q_start + radius * 2].astype(np.float64)
        r = reference[r_start - margin : r_start + radius * 2 + margin].astype(np.float64)
        if len(q) != radius * 2 or len(r) != radius * 2 + margin * 2:
            return 0.0
        q -= q.mean()
        r -= r.mean()
        norm = np.linalg.norm(q) * np.linalg.norm(r)
        if norm < 1e-8:
            return 0.0
        return float(signal.correlate(r, q, mode="valid", method="fft").max() / norm)

    for left, right in pairwise(maps):
        if not 0 <= right.start - left.end <= 12:
            continue
        times = np.arange(
            max(0.2, left.end - 0.6), min(right.start + 0.6, len(query) / sample_rate - 0.2), 0.02
        )
        if len(times) < 6:
            continue
        a = np.asarray([similarity(float(time), left) for time in times])
        b = np.asarray([similarity(float(time), right) for time in times])
        difference = a - b
        split = int(np.argmax(np.cumsum(difference)))
        before = np.flatnonzero((difference[: split + 1] > 0.12) & (a[: split + 1] > 0.3))
        after = np.flatnonzero((difference[split + 1 :] < -0.12) & (b[split + 1 :] > 0.3))
        if len(before) < 3 or len(after) < 3:
            continue
        lower, upper = times[before[-1]], times[split + 1 + after[0]]
        if upper - lower <= 0.12:
            # Local windows straddling a cut bias their centers. Locate the
            # actual sample change with a two-model residual cost instead.
            first, last = round(times[0] * sample_rate), round(times[-1] * sample_rate)
            t = np.arange(first, last) / sample_rate
            q = query[first:last].astype(np.float64)
            predicted = [
                np.interp(
                    (mapping.scale * t + mapping.offset) * sample_rate,
                    np.arange(len(reference)),
                    reference,
                )
                for mapping in (left, right)
            ]
            margin = min(len(q) // 4, round(0.3 * sample_rate))
            if margin < 1:
                continue
            gains = [
                float(
                    np.dot(q[:margin], predicted[0][:margin])
                    / max(np.dot(predicted[0][:margin], predicted[0][:margin]), 1e-10)
                ),
                float(
                    np.dot(q[-margin:], predicted[1][-margin:])
                    / max(np.dot(predicted[1][-margin:], predicted[1][-margin:]), 1e-10)
                ),
            ]
            errors = [(q - gain * value) ** 2 for gain, value in zip(gains, predicted, strict=True)]
            cost = np.cumsum(errors[0] - errors[1])
            cut = int(np.argmin(cost)) + 1
            noise = float(np.mean(errors[0][:margin]) + np.mean(errors[1][-margin:]))
            tolerance = max(noise, float(np.mean(q * q)) * 0.001) * sample_rate * 0.02
            close = np.flatnonzero(cost <= cost[cut - 1] + tolerance)
            resolution = (close[-1] - close[0] + 1) / sample_rate
            if not times[before[-1]] - 0.1 <= (first + cut) / sample_rate <= upper + 0.1:
                continue
            if resolution <= 0.08:
                left.end = right.start = (first + cut) / sample_rate
                left.boundary_uncertainty_ms = right.boundary_uncertainty_ms = resolution * 500
    return maps
