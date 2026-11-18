"""Measured user-audio run in separate storage, with restartable minutes generation."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import time
import traceback
import zipfile
from pathlib import Path


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    import soundfile as sf
    import torch

    from meeting_pipeline.adapters.phowhisper_asr import PhoWhisperAsrAdapter
    from meeting_pipeline.config import load_config
    from meeting_pipeline.minutes import graph_pipeline
    from meeting_pipeline.minutes.model_runtime import ModelSession, load_model_settings
    from meeting_pipeline.minutes.service import MinutesService
    from meeting_pipeline.minutes.text_engine import MinutesOptions
    from meeting_pipeline.pipeline.multi_source_fusion import MultiSourceFusionPipeline

    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(2)
    started = time.perf_counter()
    source_hash = sha256(args.audio)
    info = sf.info(args.audio)

    def save(name, value):
        path = output / name
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
        temp.replace(path)

    def progress(phase, **value):
        event = {"phase": phase, "elapsed_sec": round(time.perf_counter() - started, 3), **value}
        with (output / "progress.jsonl").open("a") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        print(json.dumps(event, ensure_ascii=False), flush=True)

    save(
        "input.json",
        {
            "audio": str(args.audio),
            "sha256": source_hash,
            "duration_sec": info.duration,
            "sample_rate": info.samplerate,
            "channels": info.channels,
            "bytes": args.audio.stat().st_size,
            "template": str(args.template),
            "template_sha256": sha256(args.template),
        },
    )
    summary = {
        "input_audio_sec": info.duration,
        "input_sha256": source_hash,
        "cached_asr_responses": False,
        "cached_llm_responses": False,
        "has_reference_transcript": False,
        "semantic_accuracy_verified": False,
    }
    phase = "audio"
    try:
        if args.run_dir:
            run = args.run_dir.resolve()
            summary.update(json.loads((output / "audio_summary.json").read_text()))
            progress("reuse_audio", run=str(run))
        else:
            cfg = load_config(root / "web_app/configs/default.yaml")
            cfg.paths.data_dir = output / "storage"
            cfg.paths.database_path = output / "test.sqlite"
            cfg.paths.model_cache_dir = root / "data/model_cache"
            cfg.asr.cache_enabled = False
            asr_timings = []

            class TimedAsr(PhoWhisperAsrAdapter):
                def transcribe(self, waveform, sample_rate=16000):
                    begin = time.perf_counter()
                    result = super().transcribe(waveform, sample_rate)
                    row = {
                        "index": len(asr_timings) + 1,
                        "duration_sec": len(waveform) / sample_rate,
                        "wall_sec": time.perf_counter() - begin,
                        "status": result.status,
                        "words": len(result.text.split()),
                        "warnings": result.warnings,
                        "runtime": str(getattr(self._pipeline, "device", "cpu")),
                    }
                    asr_timings.append(row)
                    progress("asr", **row)
                    save("asr_timings.json", asr_timings)
                    return result

            adapter = TimedAsr(cfg.asr, cfg.paths.model_cache_dir)
            pipeline = MultiSourceFusionPipeline(cfg, asr_adapter=adapter)
            progress("audio_started")
            begin = time.perf_counter()
            run = pipeline.run(
                "user_audio_" + source_hash[:12],
                [args.audio],
                fusion_method="F5_RULE_WEIGHTED_CORRECTED",
            )
            summary.update(audio_wall_sec=time.perf_counter() - begin, run=str(run))
            save(
                "audio_summary.json", {"audio_wall_sec": summary["audio_wall_sec"], "run": str(run)}
            )
            save("run_path.json", {"run": str(run)})
            if hasattr(adapter._pipeline, "close"):
                adapter._pipeline.close()
            del pipeline, adapter
            gc.collect()
            progress("audio_completed", wall_sec=summary["audio_wall_sec"], run=str(run))

        rows = json.loads((run / "timeline.json").read_text())["segments"]
        lines = []
        for row in rows:
            start, end = row["start_sec"], row["end_sec"]
            speaker = row.get("speaker_label") or row.get("speaker_id") or "Chưa rõ"
            text = row.get("text") or f"[Chưa nhận dạng: {row.get('asr_status', 'unknown')}]"
            lines.append(f"[{start:.2f}-{end:.2f}] {speaker}: {text}")
        (output / "transcript.txt").write_text("\n\n".join(lines))
        summary.update(
            segments=len(rows),
            transcribed_segments=sum(r.get("asr_status") == "transcribed" for r in rows),
            transcript_words=sum(len(r.get("text", "").split()) for r in rows),
            speaker_labels=sorted({str(r.get("speaker_label")) for r in rows}),
            asr_status_counts={
                status: sum(r.get("asr_status") == status for r in rows)
                for status in {r.get("asr_status") for r in rows}
            },
        )
        save("summary.json", {**summary, "state": "audio_completed"})
        phase = "minutes"

        class MeasuredSession(ModelSession):
            def __init__(self, log_path, settings=None):
                super().__init__(
                    log_path,
                    (settings or load_model_settings()).model_copy(
                        update={"response_cache": False}
                    ),
                )

            def request(self, op, **payload):
                begin = time.perf_counter()
                if op in {"chat", "chat_batch"}:
                    progress("llm_started", operation=op, completed_calls=len(self.calls))
                result = super().request(op, **payload)
                if op in {"chat", "chat_batch"}:
                    progress(
                        "llm_completed",
                        operation=op,
                        wall_sec=time.perf_counter() - begin,
                        completed_calls=len(self.calls),
                        output_tokens=result.get("generation_tokens"),
                        prefix_cache_tokens=result.get("prefix_cache_tokens", 0),
                    )
                return result

        graph_pipeline.ModelSession = MeasuredSession
        progress("minutes_started", segments=summary["segments"], words=summary["transcript_words"])
        begin = time.perf_counter()
        result = MinutesService().process_template_for_run(
            args.template,
            run,
            meeting_metadata={
                "meeting_id": "user_audio_" + source_hash[:12],
                "meeting_name": args.audio.stem.replace("_", " "),
            },
            options=MinutesOptions(
                use_model=True,
                graph_enabled=True,
                mode="general",
                correct_transcript=True,
                format_standard="minimal",
            ),
            reuse_schema=True,
        )
        summary["minutes_wall_sec"] = time.perf_counter() - begin
        with zipfile.ZipFile(result["zip_export"]) as archive:
            assert archive.testzip() is None
        report = json.loads((run / "minutes/model_report.json").read_text())
        summary.update(
            state="completed",
            total_wall_sec=summary["audio_wall_sec"] + summary["minutes_wall_sec"],
            docx=result["completed_docx"],
            zip=result["zip_export"],
            zip_integrity_passed=True,
            coverage=report["coverage"],
            graph_wall_sec=report["wall_sec"],
            graph_units=report["unit_count"],
            graph_nodes=report["node_count"],
            graph_edges=report["edge_count"],
            llm_calls=len(report["calls"]),
            original_audio_unchanged=sha256(args.audio) == source_hash,
        )
        save("summary.json", summary)
        progress(
            "completed", total_wall_sec=summary["total_wall_sec"], docx=result["completed_docx"]
        )
    except Exception as exc:
        save(
            "failure.json",
            {
                "phase": phase,
                "elapsed_sec": time.perf_counter() - started,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            },
        )
        progress("failed", error=str(exc))
        raise


if __name__ == "__main__":
    main()
