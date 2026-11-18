"""Reproduce one rejected request and keep its full response for diagnosis, not scoring."""
# ruff: noqa: E402

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "web_app/src"))

from meeting_pipeline.minutes.graph_contracts import MeetingGraph, remap_identifiers
from meeting_pipeline.minutes.graph_pipeline import save_json
from meeting_pipeline.minutes.graph_writer import WRITE_PROMPT, packet_for
from meeting_pipeline.minutes.model_runtime import ModelSession


def main():
    base = ROOT / "reports/minutes_graph/20261108"
    run = base / "ablations_v2/MINDA-FT-050-1-1/C"
    graph = MeetingGraph.model_validate(json.loads((run / "meeting_graph.json").read_text()))
    audit = json.loads((run / "verification.json").read_text())["checks"]
    plan = json.loads((run / "content_plan.json").read_text())
    style = json.loads((run / "style_profile.json").read_text())
    failed = next(row for row in audit if "JSON" in row.get("reason", ""))
    section = next(s for s in plan["sections"] if s["section_id"] == failed["section_id"])
    packet = packet_for(graph, failed["claim_ids"], use_graph=True, soft=False)
    payload = {
        **packet,
        "section_title": section["title"],
        "style": [r["instruction"] for r in style["rules"] if r["active"]],
    }
    source_ids = [row["unit_id"] for row in payload["sources"]]
    claim_ids = [row["claim_id"] for row in payload["claims"]]
    for edge in payload["relations"]:
        claim_ids.extend([edge["source"], edge["target"]])
    aliases = {uid: f"u{i}" for i, uid in enumerate(dict.fromkeys(source_ids))}
    aliases.update({cid: f"c{i}" for i, cid in enumerate(dict.fromkeys(claim_ids))})
    payload = remap_identifiers(payload, aliases)
    with ModelSession(base / "diagnostics/model_runtime.log") as session:
        result = session.request(
            "chat",
            system=WRITE_PROMPT,
            user=json.dumps(payload, ensure_ascii=False),
            max_tokens=session.settings.output_token_budget,
        )
        settings = session.settings.model_dump()
    raw = str(result["text"]).strip()
    normalized = raw
    if normalized.startswith("```"):
        normalized = normalized.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    parse_error, trailing = None, None
    try:
        _, end = json.JSONDecoder().raw_decode(normalized)
        trailing = normalized[end:]
        json.loads(normalized)
    except (ValueError, TypeError) as exc:
        parse_error = str(exc)
    report = {
        "purpose": "single deterministic-request diagnostic; not another test-quality score",
        "case": "MINDA-FT-050-1-1",
        "variant": "C",
        "settings": settings,
        "system": WRITE_PROMPT,
        "payload": payload,
        "request_sha256": hashlib.sha256(
            json.dumps([WRITE_PROMPT, payload], sort_keys=True).encode()
        ).hexdigest(),
        "response": result,
        "normalized_json_error": parse_error,
        "trailing_after_first_json_value": trailing,
    }
    save_json(base / "diagnostics/reproduced_json_failure.json", report)
    print(
        json.dumps(
            {
                "finish_reason": result.get("finish_reason"),
                "normalized_json_error": parse_error,
                "trailing": trailing,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
