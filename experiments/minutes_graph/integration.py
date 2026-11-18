"""Exercise the actual service, template fill, formatting, manifest and ZIP on existing inputs."""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "web_app/src"))

from docx import Document

from meeting_pipeline.minutes import graph_pipeline
from meeting_pipeline.minutes.doc_parser import parse_template_document
from meeting_pipeline.minutes.graph_pipeline import save_json
from meeting_pipeline.minutes.model_runtime import ModelSession
from meeting_pipeline.minutes.schema_mapper import M0RuleSchemaMapper
from meeting_pipeline.minutes.service import MinutesService
from meeting_pipeline.minutes.text_engine import MinutesOptions


class DiagnosticSession(ModelSession):
    """Unchanged inference/parser behavior; retain failed raw responses for diagnosis."""

    def request(self, op, **payload):
        result = super().request(op, **payload)
        if op == "chat":
            self.last_raw_response = result
        return result

    def generate_json(self, system, payload):
        self.last_raw_response = None
        try:
            return super().generate_json(system, payload)
        except (ValueError, TypeError, RuntimeError) as exc:
            if self.last_raw_response:
                key = hashlib.sha256(
                    json.dumps([system, payload], sort_keys=True).encode()
                ).hexdigest()
                save_json(
                    self.log_path.parent / "failed_response_diagnostics" / (key + ".json"),
                    {
                        "system": system,
                        "payload": payload,
                        "error": str(exc),
                        "response": self.last_raw_response,
                        "diagnostic_only": True,
                    },
                )
            raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", nargs="+", default=["reference", "asr"])
    parser.add_argument(
        "--output", type=Path, default=ROOT / "reports/minutes_graph/20261108/end_to_end_final"
    )
    args = parser.parse_args()
    graph_pipeline.ModelSession = DiagnosticSession
    # QA uses the bundled headless renderer, not the user's desktop LibreOffice.
    bundle = "/Users/thien/.cache/codex-runtimes/codex-primary-runtime/dependencies"
    os.environ["PATH"] = (
        bundle + "/bin/override:" + bundle + "/bin/fallback:" + os.environ.get("PATH", "")
    )
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    template = output / "minimal_template.docx"
    document = Document()
    document.add_heading("Biên bản họp triển khai kho tài liệu", level=0)
    document.add_paragraph("Địa điểm: ........................................")
    document.add_paragraph("Nội dung cuộc họp:")
    document.add_paragraph("..................................................")
    document.save(template)
    template_hash = hashlib.sha256(template.read_bytes()).hexdigest()
    schema = M0RuleSchemaMapper().propose_schema(parse_template_document(template))
    schema.proposed_by = "user_manual"
    results = []
    for kind in args.inputs:
        run = output / kind
        (run / "template").mkdir(parents=True, exist_ok=True)
        save_json(run / "template/schema.json", schema.model_dump(mode="json"))
        if kind == "reference":
            source = (
                ROOT / "data/generated/fpt_tts_pilot_20261003/meeting_audio/reference_segments.json"
            )
            rows = json.loads(source.read_text())
            timeline = {
                "segments": [
                    {
                        **r,
                        "turn_id": r["segment_id"],
                        "text": r["reference_text"],
                        "speaker_label": r["reference_speaker_id"].title(),
                        "speaker_id": r["reference_speaker_id"],
                        "asr_status": "transcribed",
                    }
                    for r in rows
                ]
            }
        else:
            source = (
                ROOT
                / "data/meetings/test-c-enroll/runs"
                / "3e27f5fa-08d8-443d-a8d3-c44ef62b1479/timeline.json"
            )
            timeline = json.loads(source.read_text())
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        save_json(run / "timeline.json", timeline)
        started = time.perf_counter()
        print("START service " + kind, flush=True)
        result = MinutesService().process_template_for_run(
            template,
            run,
            meeting_metadata={
                "meeting_id": "existing_pilot_" + kind,
                "meeting_name": "Họp triển khai kho tài liệu Sao Khuê",
                "meeting_date": "2026-10-03",
                "location": "B201",
                "agenda": ["Tổ chức tài liệu", "Phân quyền", "Phân công và tiến độ"],
            },
            options=MinutesOptions(
                use_model=True,
                graph_enabled=True,
                mode="general",
                correct_transcript=False,
                format_standard="minimal",
            ),
            reuse_schema=True,
        )
        completed = Path(result["completed_docx"])
        text = "\n".join(p.text for p in Document(completed).paragraphs)
        assert not re.search(r"\be_u_[a-f0-9]{16}\b", text)
        assert hashlib.sha256(source.read_bytes()).hexdigest() == before
        assert hashlib.sha256(template.read_bytes()).hexdigest() == template_hash
        with zipfile.ZipFile(result["zip_export"]) as package:
            assert package.testzip() is None
            assert package.read("completed.docx") == completed.read_bytes()
            for name in [
                "meeting_graph.json",
                "content_plan.json",
                "coverage.json",
                "verification.json",
            ]:
                assert name in package.namelist()
        report = result["model_report"]
        assert report["engine"] == "fcm_evidence_graph"
        assert report["coverage"]["claim_id_coverage_complete"]
        item = {
            "input": kind,
            "source_path": str(source),
            "source_sha256": before,
            "source_unchanged": True,
            "template_unchanged": True,
            "wall_sec": time.perf_counter() - started,
            "engine": report["engine"],
            "graph_id": report["graph_id"],
            "coverage": report["coverage"],
            "zip_integrity_pass": True,
            "completed_docx": str(completed),
            "formatting": result["formatting_report"],
            "semantic_accuracy_verified": False,
        }
        results.append(item)
        save_json(output / "results.json", results)
        print(
            json.dumps({k: item[k] for k in ["input", "wall_sec", "zip_integrity_pass", "engine"]}),
            flush=True,
        )


if __name__ == "__main__":
    main()
