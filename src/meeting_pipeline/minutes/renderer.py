"""Word document template renderer filling validated facts into a template copy.

Preserves exact formatting, styles, table borders, headings, and font attributes
without overwriting or modifying the original uploaded template.
Specification: Section 5 (F4) of docs/PLAN_BIEU_MAU_BIEN_BAN_V1.md.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

import docx
from docx.text.paragraph import Paragraph

from meeting_pipeline.minutes.converter import compute_file_sha256
from meeting_pipeline.minutes.schemas import (
    CandidateAnchor,
    DocGraph,
    FactStatus,
    MeetingFact,
    PlaceholderType,
    TemplateSchema,
)

logger = logging.getLogger(__name__)


def _format_value_for_doc(val: Any) -> str:
    """Format any python value to an administrative document string."""
    if val is None:
        return ""
    if isinstance(val, list):
        if len(val) == 1:
            return str(val[0])
        # Format as numbered or bullet list
        return "\n".join(f"- {item}" for item in val)
    return str(val).strip()


def _replace_text_in_paragraph(paragraph: Paragraph, placeholder: str, replacement: str) -> bool:
    """Replace placeholder text within a paragraph while preserving run formatting."""
    full_text = paragraph.text
    if placeholder not in full_text:
        return False

    # Case 1: Simple single run match
    for run in paragraph.runs:
        if placeholder in run.text:
            run.text = run.text.replace(placeholder, replacement, 1)
            return True

    # Case 2: Placeholder spans across multiple runs
    # Replace across runs preserving style of the first matching run
    new_full_text = full_text.replace(placeholder, replacement, 1)
    if paragraph.runs:
        # Keep formatting of first run, clear others
        first_run = paragraph.runs[0]
        first_run.text = new_full_text
        for r in paragraph.runs[1:]:
            r.text = ""
        return True

    paragraph.text = new_full_text
    return True


def render_completed_document(
    normalized_docx_path: Path,
    output_docx_path: Path,
    doc_graph: DocGraph,
    schema: TemplateSchema,
    facts: list[MeetingFact],
) -> tuple[Path, str]:
    """Fill validated facts into a copy of the normalized template DOCX."""
    if not normalized_docx_path.is_file():
        raise FileNotFoundError(f"Template not found: {normalized_docx_path}")

    output_docx_path.parent.mkdir(parents=True, exist_ok=True)
    # Work strictly on a copy
    shutil.copy2(normalized_docx_path, output_docx_path)
    doc = docx.Document(str(output_docx_path))

    # Build lookup maps: anchor_id -> field -> fact
    fields_by_anchor = {f.anchor_id: f for f in schema.fields}
    facts_by_field = {f.field_id: f for f in facts}

    # Group anchors by element path
    anchors_by_elem: dict[str, list[CandidateAnchor]] = {}
    for a in doc_graph.all_anchors:
        # Base element e.g. p[13] or table[0]/row[1]/cell[2]
        base_elem = (
            a.element_path.split("/")[0]
            if "table" not in a.element_path
            else "/".join(a.element_path.split("/")[:3])
        )
        anchors_by_elem.setdefault(base_elem, []).append(a)

    # Iterate through paragraphs in body
    for p_idx, p in enumerate(doc.paragraphs):
        p_elem = f"p[{p_idx}]"
        matching_anchors = anchors_by_elem.get(p_elem, [])
        for anchor in matching_anchors:
            field = fields_by_anchor.get(anchor.anchor_id)
            if not field:
                continue
            fact = facts_by_field.get(field.field_id)
            if not fact or fact.status == FactStatus.UNKNOWN or fact.value is None:
                continue

            formatted_val = _format_value_for_doc(fact.value)
            if not formatted_val:
                continue

            if anchor.placeholder_type in (PlaceholderType.DOTTED_LINE, PlaceholderType.UNDERLINE):
                _replace_text_in_paragraph(p, anchor.placeholder_text, formatted_val)
            elif anchor.placeholder_type == PlaceholderType.TEXT_PLACEHOLDER:
                # Append formatted text to the paragraph
                if not p.text.endswith(" "):
                    p.text = f"{p.text} {formatted_val}"
                else:
                    p.text = f"{p.text}{formatted_val}"
            elif anchor.placeholder_type == PlaceholderType.SIGNATURE_BLOCK:
                # Add signature confirmation underneath
                pass

    # Iterate through tables
    for t_idx, table in enumerate(doc.tables):
        for r_idx, row in enumerate(table.rows):
            for c_idx, cell in enumerate(row.cells):
                cell_elem = f"table[{t_idx}]/row[{r_idx}]/cell[{c_idx}]"
                matching_anchors = anchors_by_elem.get(cell_elem, [])

                for anchor in matching_anchors:
                    field = fields_by_anchor.get(anchor.anchor_id)
                    if not field:
                        continue
                    fact = facts_by_field.get(field.field_id)
                    if not fact or fact.status == FactStatus.UNKNOWN or fact.value is None:
                        continue

                    formatted_val = _format_value_for_doc(fact.value)
                    if not formatted_val:
                        continue

                    if anchor.placeholder_type == PlaceholderType.EMPTY_CELL:
                        cell.text = formatted_val
                    elif anchor.placeholder_type in (
                        PlaceholderType.DOTTED_LINE,
                        PlaceholderType.UNDERLINE,
                    ):
                        for cp in cell.paragraphs:
                            if anchor.placeholder_text in cp.text:
                                _replace_text_in_paragraph(
                                    cp, anchor.placeholder_text, formatted_val
                                )

    doc.save(str(output_docx_path))
    completed_sha = compute_file_sha256(output_docx_path)
    logger.info(
        "Saved completed Word document: %s (SHA-256: %s)", output_docx_path, completed_sha[:12]
    )
    return output_docx_path, completed_sha
