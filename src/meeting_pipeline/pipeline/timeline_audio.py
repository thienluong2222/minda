"""Recording-aware audio execution with explicit clock components and provenance."""

from __future__ import annotations

import csv
import json
import time
import uuid
import zipfile
from collections import Counter, defaultdict
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import soundfile as sf

from meeting_pipeline.adapters.audio_io import (
    decode_mono,
    probe_audio,
    sha256_file,
    validate_audio_duration,
)
from meeting_pipeline.audio.fingerprints import Array, Fingerprint, fingerprint
from meeting_pipeline.audio.timeline_alignment import ClockSpan, local_clock, resolve_clocks
from meeting_pipeline.config import PipelineConfig
from meeting_pipeline.domain.errors import InvalidAudioError

if TYPE_CHECKING:
    from meeting_pipeline.application.speakers import SpeakerProfileInput

Json = dict[str, Any]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


class TimelineAudioPipeline:
    def __init__(
        self, config: PipelineConfig, core_factory: Callable[[PipelineConfig], Any] | None = None
    ) -> None:
        self.config = config
        self.core_factory = core_factory
        self.sample_rate = config.audio.analysis_sample_rate

    def run(
        self,
        name: str,
        asset_paths: dict[str, Path],
        layout: Json,
        profiles: list[SpeakerProfileInput] | None = None,
        fusion_method: str = "F5_RULE_WEIGHTED_CORRECTED",
        check: Callable[[], None] | None = None,
        timeline_hash: str | None = None,
    ) -> Path:
        started = time.perf_counter()
        check = check or (lambda: None)
        root = self.config.paths.data_dir / "timeline-runs" / str(uuid.uuid4())
        root.mkdir(parents=True)
        decoded: dict[str, Json] = {}
        source_rows: list[Json] = []
        warnings: list[Json] = []
        for asset_id, path in asset_paths.items():
            check()
            metadata = probe_audio(path)
            validate_audio_duration(metadata, self.config.audio.max_duration_seconds)
            # Filenames derive from a hash, never a client-provided filesystem path.
            target = root / "decoded" / f"{len(decoded):04d}.wav"
            frames = decode_mono(path, target, self.sample_rate)
            if frames / self.sample_rate > self.config.audio.max_duration_seconds:
                raise InvalidAudioError("Decoded recording exceeds current duration limit")
            decoded[asset_id] = {"path": target, "frames": frames, "metadata": metadata}
            source_rows.append(
                {
                    "source_id": asset_id,
                    "original_name": path.name,
                    "sha256": sha256_file(path),
                    "duration_sec": frames / self.sample_rate,
                }
            )
        clips: dict[str, Json] = {clip["id"]: deepcopy(clip) for clip in layout["clips"]}
        tracks = {
            clip_id: track["id"] for track in layout["tracks"] for clip_id in track["clip_ids"]
        }
        durations = {}
        for clip_id, clip in clips.items():
            asset = decoded[clip["asset_id"]]
            actual_end = asset["frames"] / self.sample_rate
            declared_end = clip["source_out_ms"] / 1000
            metadata = asset["metadata"]
            whole_estimated_file = (
                metadata.duration_is_estimate
                and clip["source_out_ms"] >= metadata.duration_sec * 1000 - 1
            )
            # Timeline bounds are integer milliseconds rounded up by ingest.
            # Compare on that same grid, allowing one analysis sample for
            # decoder/resampler rounding, then read only real decoded samples.
            maximum_end_ms = (
                (asset["frames"] + 1) * 1000 + self.sample_rate - 1
            ) // self.sample_rate
            if clip["source_out_ms"] > maximum_end_ms and not whole_estimated_file:
                raise InvalidAudioError(
                    "Vùng audio đã chọn vượt quá thời lượng file sau giải mã. "
                    "Hãy kiểm tra điểm kết thúc của đoạn."
                )
            if whole_estimated_file and abs(declared_end - actual_end) > 1 / self.sample_rate:
                warnings.append(
                    {
                        "clip_id": clip_id,
                        "reason": "container_duration_adjusted",
                        "decoded_duration_sec": actual_end,
                    }
                )
            # A container estimate can be shorter as well as longer than the
            # decoded stream. Selecting its full range must retain the tail.
            end = actual_end if whole_estimated_file else min(declared_end, actual_end)
            start = clip["source_in_ms"] / 1000
            if end <= start:
                raise InvalidAudioError("Selected clip range is empty after decoding")
            durations[clip_id] = end - start

        def load(clip_id: str) -> Array:
            clip = clips[clip_id]
            start = round(clip["source_in_ms"] * self.sample_rate / 1000)
            with sf.SoundFile(decoded[clip["asset_id"]]["path"]) as stream:
                stream.seek(start)
                return np.asarray(
                    stream.read(round(durations[clip_id] * self.sample_rate), dtype="float32")
                )

        features: dict[str, Fingerprint] = {}
        for clip_id in clips:
            check()
            features[clip_id] = fingerprint(load(clip_id), self.sample_rate)
        report = resolve_clocks(
            layout,
            durations,
            features,
            load,
            self.sample_rate,
            self.config.sync.minimum_common_speech_seconds,
            check,
            maximum_extrapolation_sec=self.config.sync.max_offset_seconds,
        )
        spans = [ClockSpan(**value) for values in report["spans"].values() for value in values]

        # Never overwrite one recording with another if inferred order is wrong.
        by_lane: dict[tuple[str, str], list[ClockSpan]] = defaultdict(list)
        for span in spans:
            by_lane[(span.clock_id, tracks[span.clip_id])].append(span)
        report["proposed_spans"] = deepcopy(report["spans"])
        demoted = {value["clip_id"] for value in report["conflicts"] if "clip_id" in value}
        for values in by_lane.values():
            previous_end = None
            for span in sorted(values, key=lambda value: value.at(value.start)):
                if previous_end is not None and span.at(span.start) < previous_end - 0.001:
                    demoted.add(span.clip_id)
                previous_end = max(
                    previous_end if previous_end is not None else float("-inf"), span.at(span.end)
                )
        if demoted:
            while True:
                dependent = {
                    span.clip_id for span in spans if any(key in demoted for key in span.via)
                }
                if dependent <= demoted:
                    break
                demoted.update(dependent)
            spans = [span for span in spans if span.clip_id not in demoted]
            for clip_id in sorted(demoted):
                spans.append(
                    ClockSpan(
                        clip_id,
                        local_clock(clip_id),
                        0,
                        durations[clip_id],
                        1,
                        0,
                        "local",
                        via=(clip_id,),
                    )
                )
                report["conflicts"].append(
                    {"clip_id": clip_id, "reason": "same_source_coverage_conflict"}
                )
        components: dict[str, list[ClockSpan]] = defaultdict(list)
        for span in spans:
            components[span.clock_id].append(span)
        report["spans"] = {
            clip_id: [vars(span) for span in spans if span.clip_id == clip_id] for clip_id in clips
        }
        positions = {
            clip_id: (track["id"], index)
            for track in layout["tracks"]
            for index, clip_id in enumerate(track["clip_ids"])
        }
        report["clock_ids"] = sorted(
            components,
            key=lambda key: (
                key != "meeting",
                min((*positions[span.clip_id], span.start) for span in components[key]),
            ),
        )
        report["timing_complete"] = (
            list(report["clock_ids"]) == ["meeting"] and not report["conflicts"]
        )
        intervals, interval_warnings = self._intervals(layout, spans)
        report["resolved_intervals"] = intervals
        if interval_warnings:
            report["timing_complete"] = False
            warnings.extend(interval_warnings)
        origin_shift = -min(
            0.0,
            min((span.at(span.start) for span in spans if span.clock_id == "meeting"), default=0.0),
        )
        report["meeting_origin_shift_sec"] = origin_shift
        report["warnings"] = warnings
        report["estimated_span_count"] = sum(span.origin == "extrapolated" for span in spans)
        for values in components.values():
            extent = max(v.at(v.end) for v in values) - min(v.at(v.start) for v in values)
            if extent > self.config.audio.max_duration_seconds + 1 / self.sample_rate:
                raise InvalidAudioError(
                    "Timeline clock span exceeds current processing limit; "
                    "long processing is step 4"
                )
        write_json(root / "alignment.json", report)
        config = self.config.model_copy(deep=True)
        config.paths.data_dir = root / "components"
        if self.core_factory is None:
            from meeting_pipeline.pipeline.multi_source_fusion import MultiSourceFusionPipeline

            core = MultiSourceFusionPipeline(config)
        else:
            core = self.core_factory(config)
        rows: list[Json] = []
        runs: list[Json] = []
        models: Json = {}
        enrolled_ids = {profile.speaker_id for profile in profiles or []}
        for number, clock in enumerate(report["clock_ids"], start=1):
            check()
            values = components[clock]
            begin = min(span.at(span.start) for span in values)
            end = max(span.at(span.end) for span in values)
            paths, sync, boundaries, source_tracks = self._render(
                root,
                number,
                values,
                clips,
                tracks,
                decoded,
                begin,
                end,
            )
            for interval in intervals:
                if interval["clock_id"] == clock:
                    boundaries.extend([interval["start_sec"] - begin, interval["end_sec"] - begin])
            run = core.run(
                f"{name}-clock-{number}",
                paths,
                profiles,
                fusion_method=fusion_method,
                prepared_sync=sync,
                hard_boundaries=[value for value in boundaries if 0 <= value <= end - begin],
                include_archive=False,
            )
            check()
            prefix = run.relative_to(root).as_posix()
            manifest = json.loads((run / "manifest.json").read_text())
            models.update(manifest.get("models", {}))
            runs.append(
                {
                    "clock_id": clock,
                    "run_path": prefix,
                    "origin_sec": begin,
                    "duration_sec": end - begin,
                    "asr_input_stats": manifest.get("asr_input_stats", {}),
                }
            )
            for raw in json.loads((run / "timeline.json").read_text()).get("segments", []):
                row = self._project_row(
                    raw,
                    prefix,
                    clock,
                    begin,
                    origin_shift,
                    values,
                    clips,
                    tracks,
                    source_tracks,
                    intervals,
                    number,
                )
                row["needs_review"] = bool(row.get("needs_review") or not report["timing_complete"])
                row["timing_complete"] = report["timing_complete"]
                if row.get("speaker_id") not in enrolled_ids:
                    for key in ("speaker_id", "meeting_speaker_id", "track_id"):
                        if row.get(key):
                            row[key] = f"{clock}:{row[key]}"
                rows.append(row)
        stats: Counter[str] = Counter()
        for component in runs:
            stats.update(component.get("asr_input_stats", {}))
        report["component_runs"] = runs
        write_json(root / "alignment.json", report)
        write_json(
            root / "timeline.json",
            {
                "schema_version": "3.0",
                "segments": rows,
                "timing_complete": report["timing_complete"],
            },
        )
        elapsed = max(
            (span.at(span.end) + origin_shift for span in spans if span.clock_id == "meeting"),
            default=0.0,
        )
        write_json(
            root / "manifest.json",
            {
                "schema_version": "3.0",
                "run_id": root.name,
                "meeting_name": name,
                "backend": "recording_timeline",
                "asr_fusion_mode": self.config.asr.fusion_mode,
                "asr_input_stats": dict(stats),
                "status": "succeeded",
                "sources": source_rows,
                "models": models,
                "timing_complete": report["timing_complete"],
                "duration_sec": elapsed if report["timing_complete"] else None,
                "recorded_component_duration_sec": sum(run["duration_sec"] for run in runs),
                "component_count": len(runs),
                "timings": {"total_sec": time.perf_counter() - started},
            },
        )
        write_json(
            root / "input_timeline.json",
            {
                "timeline_hash": timeline_hash,
                "timeline": layout,
                "processing_mode": "timeline",
                "source_assets": {asset_id: asset_id for asset_id in asset_paths},
            },
        )
        self._exports(root, rows, report)
        return root

    @staticmethod
    def _intervals(layout: Json, spans: list[ClockSpan]) -> tuple[list[Json], list[Json]]:
        resolved: list[Json] = []
        warnings: list[Json] = []
        for interval in layout.get("intervals", []):
            clocks, bounds = [], []
            for side in ("start", "end"):
                explicit = interval.get(f"{side}_ms")
                if explicit is not None:
                    clocks.append("meeting")
                    bounds.append(explicit / 1000)
                    continue
                candidates = [
                    span for span in spans if span.clip_id == interval.get(f"{side}_clip_id")
                ]
                if not candidates:
                    break
                span = (
                    min(candidates, key=lambda v: v.start)
                    if side == "start"
                    else max(candidates, key=lambda v: v.end)
                )
                clocks.append(span.clock_id)
                bounds.append(span.at(span.start if side == "start" else span.end))
            if len(bounds) != 2 or clocks[0] != clocks[1] or bounds[1] <= bounds[0]:
                warnings.append(
                    {"interval_id": interval["id"], "reason": "interval_clock_unresolved"}
                )
            else:
                resolved.append(
                    {
                        **interval,
                        "clock_id": clocks[0],
                        "start_sec": bounds[0],
                        "end_sec": bounds[1],
                    }
                )
        return resolved, warnings

    def _render(
        self,
        root: Path,
        number: int,
        spans: list[ClockSpan],
        clips: dict[str, Json],
        tracks: dict[str, str],
        decoded: dict[str, Json],
        begin: float,
        end: float,
    ) -> tuple[list[Path], dict[str, Json], list[float], dict[str, str]]:
        by_track: dict[str, list[ClockSpan]] = defaultdict(list)
        for span in spans:
            by_track[tracks[span.clip_id]].append(span)
        length = round((end - begin) * self.sample_rate)
        paths: list[Path] = []
        metadata: dict[str, Json] = {}
        boundaries: list[float] = []
        source_tracks: dict[str, str] = {}
        for index, track_id in enumerate(sorted(by_track), start=1):
            source_id = f"source-{index}"
            source_tracks[source_id] = track_id
            waveform = np.zeros(length, dtype=np.float32)
            coverages: list[list[float]] = []
            segments: list[Json] = []
            for span in by_track[track_id]:
                clip = clips[span.clip_id]
                start = max(0, round((span.at(span.start) - begin) * self.sample_rate))
                stop = min(length, round((span.at(span.end) - begin) * self.sample_rate))
                input_start = round((clip["source_in_ms"] / 1000 + span.start) * self.sample_rate)
                input_end = round((clip["source_in_ms"] / 1000 + span.end) * self.sample_rate)
                with sf.SoundFile(decoded[clip["asset_id"]]["path"]) as stream:
                    stream.seek(input_start)
                    chunk = stream.read(input_end - input_start, dtype="float32")
                if stop <= start or not len(chunk):
                    continue
                if len(chunk) == stop - start:
                    waveform[start:stop] = chunk
                else:
                    waveform[start:stop] = np.interp(
                        np.linspace(0, len(chunk) - 1, stop - start),
                        np.arange(len(chunk)),
                        chunk,
                    )
                a, b = start / self.sample_rate, stop / self.sample_rate
                coverages.append([a, b])
                segments.append(
                    {
                        "start_sec": a,
                        "end_sec": b,
                        "status": "aligned"
                        if span.origin == "acoustic"
                        else "reference"
                        if span.origin in {"local", "reference"}
                        else "declared",
                        "residual_ms": span.residual_ms,
                        "clip_id": span.clip_id,
                        "timing_origin": span.origin,
                    }
                )
            # Alignment knots inside one recording describe its clock mapping,
            # not a pause in capture. Keep real file edges and gaps hard.
            for clip_id in {segment["clip_id"] for segment in segments}:
                coverage = sorted(
                    (segment["start_sec"], segment["end_sec"])
                    for segment in segments
                    if segment["clip_id"] == clip_id
                )
                left, right = coverage[0]
                for a, b in coverage[1:]:
                    if a <= right + 1 / self.sample_rate:
                        right = max(right, b)
                    else:
                        boundaries.extend([left, right])
                        left, right = a, b
                boundaries.extend([left, right])
            target = root / "rendered" / f"clock-{number}" / f"{index}.wav"
            target.parent.mkdir(parents=True, exist_ok=True)
            sf.write(target, waveform, self.sample_rate, subtype="FLOAT")
            paths.append(target)
            metadata[source_id] = {
                "status": "timeline",
                "offset_sec": 0.0,
                "drift_ppm": 0.0,
                "residual_ms": None,
                "valid_coverage_intervals": coverages,
                "valid_coverage_interval": [
                    min(a for a, b in coverages),
                    max(b for a, b in coverages),
                ],
                "segments": segments,
            }
        return paths, metadata, boundaries, source_tracks

    def _project_row(
        self,
        raw: Json,
        prefix: str,
        clock: str,
        begin: float,
        shift: float,
        spans: list[ClockSpan],
        clips: dict[str, Json],
        tracks: dict[str, str],
        source_tracks: dict[str, str],
        intervals: list[Json],
        number: int,
    ) -> Json:
        def paths(value: Any, key: str = "") -> Any:
            if isinstance(value, dict):
                return {name: paths(child, name) for name, child in value.items()}
            if isinstance(value, list):
                return [paths(child, key) for child in value]
            if (
                isinstance(value, str)
                and value
                and (key.endswith("_artifact_id") or key.endswith("_artifact_ids"))
            ):
                if not Path(value).is_absolute():
                    return f"{prefix}/{value}"
            return value

        row: Json = paths(deepcopy(raw))
        a, b = float(raw["start_sec"]) + begin, float(raw["end_sec"]) + begin
        original_id = raw.get("turn_id") or raw["segment_id"]
        row.update(
            segment_id=f"{clock}:{original_id}",
            turn_id=f"{clock}:{original_id}",
            clock_id=clock,
            clock_label="Cuộc họp" if clock == "meeting" else f"Phần {number}",
            time_status="meeting" if clock == "meeting" else "unresolved",
            meeting_start_sec=a + shift if clock == "meeting" else None,
            meeting_end_sec=b + shift if clock == "meeting" else None,
            start_sec=a + shift if clock == "meeting" else a,
            end_sec=b + shift if clock == "meeting" else b,
            component_timebase={
                "clock_id": clock,
                "origin_sec": begin,
                "original_start_sec": raw["start_sec"],
                "original_end_sec": raw["end_sec"],
            },
        )
        evidence = []
        for span in spans:
            left, right = max(a, span.at(span.start)), min(b, span.at(span.end))
            if right - left < 0.5 / self.sample_rate:
                continue
            clip = clips[span.clip_id]
            source_start = clip["source_in_ms"] / 1000 + (left - span.offset) / span.scale
            source_end = clip["source_in_ms"] / 1000 + (right - span.offset) / span.scale
            evidence.append(
                {
                    "asset_id": clip["asset_id"],
                    "clip_id": span.clip_id,
                    "source_track_id": tracks[span.clip_id],
                    "source_start_sec": source_start,
                    "source_end_sec": source_end,
                    "source_start_sample": round(source_start * self.sample_rate),
                    "source_end_sample": round(source_end * self.sample_rate),
                    "decoded_sample_rate": self.sample_rate,
                    "mapping_scale": span.scale,
                    "mapping_offset_sec": span.offset,
                    "timing_origin": span.origin,
                    "residual_ms": span.residual_ms,
                }
            )
        row["recording_evidence"] = evidence
        selected = source_tracks.get(str(raw.get("selected_source_id") or ""))
        row["selected_recording_evidence"] = [
            value for value in evidence if value["source_track_id"] == selected
        ]
        if clock == "meeting" and any(
            value["timing_origin"] == "extrapolated" for value in row["selected_recording_evidence"]
        ):
            row["time_status"] = "estimated"
            row["needs_review"] = True
        row["interval_ids"] = [
            interval["id"]
            for interval in intervals
            if interval["clock_id"] == clock
            and interval["start_sec"] <= a + 1e-5
            and interval["end_sec"] >= b - 1e-5
        ]
        row["excluded_from_minutes"] = any(
            interval["kind"] == "excluded" and interval["id"] in row["interval_ids"]
            for interval in intervals
        )
        for selected_span in row.get("selected_spans", []):
            selected_span["interval"] = {"start_sec": row["start_sec"], "end_sec": row["end_sec"]}
        return row

    @staticmethod
    def _exports(root: Path, rows: list[Json], report: Json) -> None:
        exports = root / "exports"
        write_json(
            exports / "result.json",
            {
                "schema_version": "3.0",
                "segments": rows,
                "timing_complete": report["timing_complete"],
            },
        )
        with (exports / "result.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["clock_id", "time_status", "start_sec", "end_sec", "speaker", "text"])
            writer.writerows(
                [
                    row["clock_id"],
                    row["time_status"],
                    row["start_sec"],
                    row["end_sec"],
                    row.get("speaker_label", ""),
                    row.get("text", ""),
                ]
                for row in rows
            )
        with (exports / "result.txt").open("w", encoding="utf-8") as stream:
            if not report["timing_complete"]:
                stream.write(
                    "Còn phần chưa căn được vào đồng hồ chung; thời gian mỗi phần là cục bộ.\n"
                )
            for row in rows:
                stream.write(
                    f"[{row['clock_label']} {row['start_sec']:.2f}-{row['end_sec']:.2f}] "
                    f"{row.get('speaker_label', '')}: {row.get('text', '')}\n"
                )
        with zipfile.ZipFile(exports / "result.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(root.rglob("*")):
                if (
                    path.is_file()
                    and path.suffix != ".zip"
                    and (path.parent == root or path.parent == exports or "clips" in path.parts)
                ):
                    archive.write(path, path.relative_to(root))
