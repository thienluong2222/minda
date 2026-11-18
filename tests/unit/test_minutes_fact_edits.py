"""Regression coverage for provenance-preserving partial fact edits."""

import pytest

from meeting_pipeline.minutes.fact_edits import merge_fact_edits
from meeting_pipeline.minutes.schemas import EvidenceRef, MeetingFact


def sample_facts():
    return [
        MeetingFact(
            field_id="attendees",
            value=["Minh", "Lan"],
            status="needs_review",
            evidence_refs=[EvidenceRef(run_id="r", turn_id="seg_0000")],
            confidence=0.8,
        ),
        MeetingFact(field_id="location", value="B201", status="supported"),
    ]


def test_noop_does_not_change_evidence_types_status_or_revision():
    facts = sample_facts()
    before = [f.model_dump() for f in facts]
    after = merge_fact_edits(facts, [{"field_id": f.field_id, "value": f.value} for f in facts])
    assert [f.model_dump() for f in after] == before


def test_partial_edit_retains_other_fields_and_source_evidence():
    facts = sample_facts()
    after = merge_fact_edits(facts, [{"field_id": "attendees", "value": ["Minh"]}])
    assert after[0].evidence_refs == facts[0].evidence_refs
    assert after[0].confidence == facts[0].confidence
    assert after[0].status == "needs_review"
    assert after[0].user_edited and after[0].transcript_revision == 2
    assert after[1] == facts[1]


@pytest.mark.parametrize(
    "patches",
    [
        [{"field_id": "missing", "value": "x"}],
        [{"field_id": "location", "value": "x"}, {"field_id": "location", "value": "y"}],
    ],
)
def test_unknown_or_duplicate_fields_rejected(patches):
    with pytest.raises(ValueError):
        merge_fact_edits(sample_facts(), patches)
