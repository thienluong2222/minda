"""Unit tests for Phase F2: Schema proposal, M0 rules, M1 adapter, and schema validation."""

from __future__ import annotations

from pathlib import Path

from meeting_pipeline.minutes.converter import normalize_template
from meeting_pipeline.minutes.doc_parser import parse_template_document
from meeting_pipeline.minutes.schema_mapper import (
    M0RuleSchemaMapper,
    M1Qwen3SchemaMapper,
    SchemaValidator,
)
from meeting_pipeline.minutes.schemas import SemanticFieldType, TemplateField

FIXTURES_DIR = Path("tests/fixtures/templates")


def test_m0_schema_proposal_mau_bien_ban_hop_chung(tmp_path: Path) -> None:
    """M0 produces a valid schema matching key Vietnamese administrative semantics."""
    doc_path = FIXTURES_DIR / "mau_bien_ban_hop_chung.doc"
    converted = normalize_template(doc_path, tmp_path / "norm")
    graph = parse_template_document(converted.normalized_docx_path)

    mapper = M0RuleSchemaMapper()
    schema = mapper.propose_schema(graph)

    assert len(schema.fields) > 15
    types = {f.semantic_type for f in schema.fields}
    assert SemanticFieldType.ORGANIZATION in types
    assert SemanticFieldType.PERSON_NAME in types
    assert SemanticFieldType.PERSON_ROLE in types
    assert SemanticFieldType.MEETING_LOCATION in types
    assert SemanticFieldType.VOTING_TOTAL in types
    assert SemanticFieldType.VOTING_APPROVED_COUNT in types
    assert SemanticFieldType.VOTING_REJECTED_COUNT in types

    # Verify every anchor in schema belongs to doc_graph
    valid_ids = {a.anchor_id for a in graph.all_anchors}
    for field in schema.fields:
        assert field.anchor_id in valid_ids


def test_m0_schema_proposal_bien_ban_hop_chi_bo(tmp_path: Path) -> None:
    """M0 recognizes Party-specific meeting fields in bien_ban_hop_chi_bo."""
    docx_path = FIXTURES_DIR / "bien_ban_hop_chi_bo.docx"
    converted = normalize_template(docx_path, tmp_path / "norm")
    graph = parse_template_document(converted.normalized_docx_path)

    mapper = M0RuleSchemaMapper()
    schema = mapper.propose_schema(graph)

    types = {f.semantic_type for f in schema.fields}
    assert SemanticFieldType.PARTY_DUES in types
    assert SemanticFieldType.PARTY_MEMBER_STATUS in types
    assert SemanticFieldType.MORAL_STUDY in types
    assert SemanticFieldType.ORGANIZATION in types


def test_schema_validator_catches_hallucinated_anchor(tmp_path: Path) -> None:
    """Validator strictly rejects any anchor ID not present in DocGraph."""
    doc_path = FIXTURES_DIR / "mau_bien_ban_hop_chung.doc"
    converted = normalize_template(doc_path, tmp_path / "norm")
    graph = parse_template_document(converted.normalized_docx_path)

    bad_field = TemplateField(
        field_id="fake_field",
        anchor_id="anc_invented_9999",
        raw_label="Fake",
        semantic_type=SemanticFieldType.CUSTOM,
    )

    validated, _unmapped, issues = SchemaValidator.validate(graph, [bad_field])
    assert len(validated) == 0
    assert any("tham chiếu đến anchor không tồn tại" in iss for iss in issues)


def test_schema_validator_catches_duplicate_anchor(tmp_path: Path) -> None:
    """Validator detects when multiple fields point to the exact same anchor."""
    doc_path = FIXTURES_DIR / "mau_bien_ban_hop_chung.doc"
    converted = normalize_template(doc_path, tmp_path / "norm")
    graph = parse_template_document(converted.normalized_docx_path)
    real_anc = graph.all_anchors[0].anchor_id

    field1 = TemplateField(field_id="f1", anchor_id=real_anc, raw_label="L1")
    field2 = TemplateField(field_id="f2", anchor_id=real_anc, raw_label="L2")

    validated, _unmapped, issues = SchemaValidator.validate(graph, [field1, field2])
    assert len(validated) == 2
    assert any("bị trùng lặp" in iss for iss in issues)
    assert validated[1].mapper_status == "needs_review"


def test_m1_adapter_clean_not_run_when_weights_absent(tmp_path: Path) -> None:
    """M1 adapter accurately reports not_run status when weights are absent."""
    doc_path = FIXTURES_DIR / "mau_bien_ban_hop_chung.doc"
    converted = normalize_template(doc_path, tmp_path / "norm")
    graph = parse_template_document(converted.normalized_docx_path)

    m1 = M1Qwen3SchemaMapper()
    schema, status, duration = m1.propose_schema(graph)

    assert schema is None
    assert status == "not_run"
    assert duration >= 0.0
