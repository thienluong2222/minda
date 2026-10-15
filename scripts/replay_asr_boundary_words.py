"""Replay accepted ASR candidates through boundary ownership without model inference."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import jiwer

from meeting_pipeline.adapters.phowhisper_asr import AsrResult
from meeting_pipeline.asr.boundary_words import (
    BOUNDARY_POLICY_VERSION,
    DecodedChunk,
    filter_boundary_words,
    reconcile_internal_chunks,
    refresh_boundary_hypothesis,
)
from meeting_pipeline.domain.contracts import SourceHypothesis
from meeting_pipeline.domain.transcription import TimedWord
from meeting_pipeline.fusion.confusion_network import build_confusion_network
from meeting_pipeline.fusion.model import LearnedFusionModel
from meeting_pipeline.pipeline.multi_source_fusion import MultiSourceFusionPipeline


def normalize(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", "", unicodedata.normalize("NFC", text).casefold()).split())


def metrics(reference: str, hypothesis: str) -> dict[str, float | int]:
    result = jiwer.process_words(normalize(reference), normalize(hypothesis))
    return {
        "wer": result.wer,
        "cer": jiwer.cer(normalize(reference), normalize(hypothesis)),
        "substitutions": result.substitutions,
        "deletions": result.deletions,
        "insertions": result.insertions,
    }


def replay(run: Path, output: Path, reference_file: Path | None) -> dict[str, Any]:
    run, output = run.resolve(), output.resolve()
    if output == run or run in output.parents:
        raise ValueError("Replay output must be outside the source run.")
    watched = [run / name for name in ["timeline.json", "source_hypotheses.json", "manifest.json"]]
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in watched}
    timeline = json.loads((run / "timeline.json").read_text())["segments"]
    source_rows = json.loads((run / "source_hypotheses.json").read_text())["segments"]
    manifest = json.loads((run / "manifest.json").read_text())
    if manifest["fusion_method_used"] == "F6_LEARNED":
        raise ValueError("Replay F6 requires its original learned artifact; use a supported run.")
    coverage = json.loads((run / "coverage.json").read_text())
    merged_path = run / "merged_speaker_turns.json"
    merged = json.loads(merged_path.read_text())["turns"] if merged_path.is_file() else []
    group_ids = {row["turn_id"]: row.get("asr_chunk_group_id") for row in merged}
    chunks: list[DecodedChunk] = []
    skipped: list[dict[str, str]] = []
    for index, row in enumerate(source_rows):
        turn_id = row.get("turn_id", row["segment_id"])
        group = group_ids.get(turn_id)
        metadata = dict(row.get("routing_metadata") or {})
        metadata.update(turn_id=turn_id, asr_chunk_group_id=group)
        sources = {
            source_id: SourceHypothesis.model_validate(data)
            for source_id, data in row.get("sources", {}).items()
        }
        if "core_interval" not in metadata or "clip_interval" not in metadata:
            chunks.append((sources, metadata))
            continue
        left_internal = bool(
            group and index and group_ids.get(source_rows[index - 1]["turn_id"]) == group
        )
        right_internal = bool(
            group
            and index + 1 < len(source_rows)
            and group_ids.get(source_rows[index + 1]["turn_id"]) == group
        )
        metadata.update(
            word_boundary_policy=BOUNDARY_POLICY_VERSION,
            start_boundary_kind="internal" if left_internal else "speaker_or_silence",
            end_boundary_kind="internal" if right_internal else "speaker_or_silence",
        )
        for source_id, hypothesis in sources.items():
            if hypothesis.asr_status != "transcribed":
                continue
            accepted = [
                c
                for c in hypothesis.raw_asr_candidates
                if c.get("quality", {}).get("accepted") is True
            ]
            if not accepted:
                skipped.append(
                    {
                        "turn_id": turn_id,
                        "source_id": source_id,
                        "reason": "no_explicitly_accepted_raw_candidate",
                    }
                )
                continue
            candidate = accepted[-1]
            result = AsrResult(
                text=candidate["text"],
                words=[TimedWord.model_validate(w) for w in candidate["words"]],
                status="transcribed",
            )
            words, audit = filter_boundary_words(
                result,
                turn_id=turn_id,
                core=tuple(metadata["core_interval"]),
                clip=tuple(metadata["clip_interval"]),
                internal_start=left_internal,
                internal_end=right_internal,
                end_inclusive=not right_internal,
            )
            hypothesis.words, hypothesis.word_boundary_audit = words, audit
            refresh_boundary_hypothesis(hypothesis)
        chunks.append((sources, metadata))
    index = 0
    while index < len(chunks):
        end = index + 1
        group = chunks[index][1].get("asr_chunk_group_id")
        while group and end < len(chunks) and chunks[end][1].get("asr_chunk_group_id") == group:
            end += 1
        reconcile_internal_chunks(chunks[index:end])
        index = end
    original_by_id = {row.get("turn_id", row["segment_id"]): row for row in timeline}
    rows = []
    for sources, metadata in chunks:
        turn_id = metadata["turn_id"]
        original = original_by_id[turn_id]
        if not sources:
            text = original.get("text", "")
        else:
            MultiSourceFusionPipeline._apply_cross_source_agreement(sources)
            text, _ = MultiSourceFusionPipeline._fuse(
                manifest["fusion_method_used"],
                sources,
                build_confusion_network(sources),
                LearnedFusionModel(),
                coverage["reference_source_id"],
            )
        rows.append(
            {
                "turn_id": turn_id,
                "before_text": original.get("text", ""),
                "after_text": text,
                "routing_metadata": metadata,
                "sources": {sid: hyp.model_dump() for sid, hyp in sources.items()},
            }
        )
    report: dict[str, Any] = {
        "source_run": str(run),
        "policy_version": BOUNDARY_POLICY_VERSION,
        "model_inference": False,
        "scope": "Diagnostic replay; speaker labels/boundaries unchanged.",
        "skipped_sources": skipped,
        "rows": rows,
    }
    if reference_file:
        reference_data = json.loads(reference_file.read_text())
        reference_rows = (
            reference_data if isinstance(reference_data, list) else reference_data["turns"]
        )
        reference = " ".join(
            row.get("reference_text", row.get("text_normalized", row.get("text_raw", "")))
            for row in reference_rows
        )
        before = " ".join(row.get("text", "") for row in timeline)
        after = " ".join(row["after_text"] for row in rows)
        report.update(
            reference_units=len(normalize(reference).split()),
            before=metrics(reference, before),
            after=metrics(reference, after),
        )
    report["source_hashes_unchanged"] = all(
        hashlib.sha256(path.read_bytes()).hexdigest() == hashes[path.name] for path in watched
    )
    assert report["source_hashes_unchanged"]
    output.mkdir(parents=True, exist_ok=True)
    (output / "boundary_replay.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    (output / "transcript_after.txt").write_text("\n".join(row["after_text"] for row in rows))
    print(
        json.dumps({k: v for k, v in report.items() if k != "rows"}, ensure_ascii=False, indent=2)
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    args = parser.parse_args()
    replay(args.run_dir, args.output, args.reference)


if __name__ == "__main__":
    main()
