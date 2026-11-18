"""Apply a presentation-only fix through the actual service and verify lineage/ZIP integrity."""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "web_app/src"))

from docx import Document

from meeting_pipeline.minutes.service import MinutesService
from meeting_pipeline.minutes.text_engine import MinutesOptions


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--inputs", nargs="+", choices=["reference", "asr"], default=["reference", "asr"]
    )
    args = parser.parse_args()
    bundle = "/Users/thien/.cache/codex-runtimes/codex-primary-runtime/dependencies"
    os.environ["PATH"] = (
        bundle + "/bin/override:" + bundle + "/bin/fallback:" + os.environ.get("PATH", "")
    )
    output = ROOT / "reports/minutes_graph/20261108"
    audit_path = output / "export_reformat_audit.json"
    audit = json.loads(audit_path.read_text()) if audit_path.exists() else {}
    for kind in args.inputs:
        run = output / "end_to_end_final" / kind
        docx = run / "exports/completed.docx"
        before_text = [p.text for p in Document(docx).paragraphs]
        before_facts = json.loads((run / "minutes/facts.json").read_text())
        before_report = json.loads((run / "minutes/model_report.json").read_text())
        before_hash = sha(docx)
        immutable = {
            str(p): sha(p) for p in [run / "timeline.json", run / "template/normalized.docx"]
        }
        options = MinutesOptions.model_validate(
            json.loads((run / "minutes/configuration.json").read_text())
        )
        MinutesService().reformat_existing(
            run, options.model_copy(update={"format_standard": "minimal"})
        )
        assert [p.text for p in Document(docx).paragraphs] == before_text
        assert json.loads((run / "minutes/facts.json").read_text()) == before_facts
        after_report = json.loads((run / "minutes/model_report.json").read_text())
        assert before_report["calls"] == after_report["calls"]
        assert before_report["graph_id"] == after_report["graph_id"]
        assert all(sha(Path(p)) == h for p, h in immutable.items())
        manifest = json.loads((run / "minutes/manifest.json").read_text())
        assert manifest["completed_docx_sha256"] == sha(docx)
        with zipfile.ZipFile(run / "exports/completed_minutes.zip") as archive:
            assert archive.testzip() is None
            assert archive.read("completed.docx") == docx.read_bytes()
            assert json.loads(archive.read("manifest.json")) == manifest
            assert "meeting_graph.json" in archive.namelist()
        audit[kind] = {
            "llm_rerun": False,
            "all_paragraph_text_unchanged": True,
            "facts_and_graph_unchanged": True,
            "source_and_template_unchanged": True,
            "zip_integrity_pass": True,
            "docx_sha256_before": before_hash,
            "docx_sha256_after": sha(docx),
        }
        audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2))
        print(json.dumps({"input": kind, **audit[kind]}), flush=True)


if __name__ == "__main__":
    main()
