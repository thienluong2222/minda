"""Serialize source facts separately from template-specific field assignments."""

from typing import Any

from meeting_pipeline.minutes.evidence_retrieval import IndexedTurn
from meeting_pipeline.minutes.factuality import numeric_claims, statement_kind
from meeting_pipeline.minutes.structured_fields import extract_meeting_record
from meeting_pipeline.minutes.transcript_context import context_spans, evidence_refs


def build_meeting_record(turns: list[IndexedTurn], run_id: str) -> dict[str, Any]:
    facts, rounds = extract_meeting_record(turns, run_id)
    return {
        "schema_version": "1.0",
        "facts": {key: fact.model_dump(mode="json") for key, fact in facts.items()},
        "vote_rounds": [
            {key: fact.model_dump(mode="json") for key, fact in group.items()} for group in rounds
        ],
        "statements": [
            {
                "kind": statement_kind(span.text),
                "text": span.text,
                "claims": [
                    {"kind": kind, "value": value, "predicate": predicate, "count": count}
                    for (kind, value, predicate), count in numeric_claims(span.text).items()
                ],
                "evidence_refs": [
                    ref.model_dump(mode="json") for ref in evidence_refs(span.sources(), run_id)
                ],
            }
            for span in context_spans(turns)
        ],
    }
