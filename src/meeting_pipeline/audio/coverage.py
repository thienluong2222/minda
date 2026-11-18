"""Half-open recorded intervals; padding and capture gaps are not recorded audio."""

from __future__ import annotations

from typing import Any


def recorded_intervals(
    metadata: dict[str, Any], fallback: tuple[float, float]
) -> list[tuple[float, float]]:
    if "valid_coverage_intervals" in metadata:
        values = metadata["valid_coverage_intervals"]
    else:
        values = [metadata.get("valid_coverage_interval", fallback)]
    return sorted((float(a), float(b)) for a, b in values if b > a)


def intersect_recorded(
    intervals: list[tuple[float, float]], coverage: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    return [
        (max(a, c), min(b, d)) for a, b in intervals for c, d in coverage if min(b, d) > max(a, c)
    ]


def covers(metadata: dict[str, Any], start: float, end: float) -> bool:
    intervals = recorded_intervals(metadata, (start, end))
    cursor = start
    for a, b in intervals:
        if b < cursor - 1e-6:
            continue
        if a > cursor + 1e-6:
            return False
        cursor = max(cursor, b)
        if cursor >= end - 1e-6:
            return True
    return False


def interval_metadata(metadata: dict[str, Any], start: float, end: float) -> dict[str, Any]:
    for segment in metadata.get("segments", []):
        if segment["start_sec"] <= start + 1e-6 and segment["end_sec"] >= end - 1e-6:
            return {**metadata, **segment}
    return metadata
