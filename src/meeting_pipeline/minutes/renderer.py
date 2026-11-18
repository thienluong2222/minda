"""Word document template renderer filling validated facts into a template copy.

Preserves exact formatting, styles, table borders, headings, and font attributes
without overwriting or modifying the original uploaded template.
Specification: Section 5 (F4) of docs/PLAN_BIEU_MAU_BIEN_BAN_V1.md.
"""

from __future__ import annotations

import logging
import re
import shutil
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Any

import docx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.table import Table
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


def _replace_text_in_paragraph(
    paragraph: Paragraph, placeholder: str, replacement: str, start_offset: int | None = None
) -> bool:
    """Replace placeholder text within a paragraph while preserving run formatting."""
    full_text = paragraph.text
    if placeholder not in full_text:
        return False
    # Replace only the intersecting span; preserve labels and their run formatting.
    start = full_text.index(placeholder) if start_offset is None else start_offset
    end = start + len(placeholder)
    if full_text[start:end] != placeholder:
        return False
    offset = 0
    inserted = False
    for run in paragraph.runs:
        text = run.text
        run_end = offset + len(text)
        if offset < end and run_end > start:
            left = max(0, start - offset)
            right = min(len(text), end - offset)
            run.text = text[:left] + (replacement if not inserted else "") + text[right:]
            inserted = True
        offset = run_end
    if not inserted:
        return False
    return True


def _fill_multiline(
    paragraph: Paragraph, placeholder: str, value: str, native_headings: bool
) -> None:
    """Create editable paragraphs inside the allowed slot, cloning template styles."""
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if not lines:
        _replace_text_in_paragraph(paragraph, placeholder, "")
        return
    prefix = paragraph.text.replace(placeholder, "", 1).strip()
    rpr = (
        deepcopy(paragraph.runs[0]._r.rPr)
        if paragraph.runs and paragraph.runs[0]._r.rPr is not None
        else None
    )
    ppr = deepcopy(paragraph._p.pPr) if paragraph._p.pPr is not None else None
    if prefix:
        _replace_text_in_paragraph(paragraph, placeholder, "")
        previous = paragraph
    else:
        _replace_text_in_paragraph(paragraph, placeholder, lines.pop(0))
        previous = paragraph
        if native_headings and re.match(r"^\d+\.\s", paragraph.text):
            for run in paragraph.runs:
                run.bold = True
            paragraph.paragraph_format.keep_with_next = True
            outline = OxmlElement("w:outlineLvl")
            outline.set(qn("w:val"), "2")
            paragraph._p.get_or_add_pPr().append(outline)
    for line in lines:
        element = OxmlElement("w:p")
        if ppr is not None:
            element.append(deepcopy(ppr))
        previous._p.addnext(element)
        current = Paragraph(element, paragraph._parent)
        run = current.add_run(line)
        if rpr is not None:
            run._r.insert(0, deepcopy(rpr))
        if native_headings and re.match(r"^\d+\.\s", line):
            run.bold = True
            current.paragraph_format.keep_with_next = True
            # Native outline entry without replacing the template's named styles.
            outline = OxmlElement("w:outlineLvl")
            outline.set(qn("w:val"), "2")
            current._p.get_or_add_pPr().append(outline)
        previous = current


def render_completed_document(
    normalized_docx_path: Path,
    output_docx_path: Path,
    doc_graph: DocGraph,
    schema: TemplateSchema,
    facts: list[MeetingFact],
    general_content_field_id: str | None = None,
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

    paragraphs = {}
    cells = {}

    def walk(container, prefix=""):
        p_idx = t_idx = 0
        for element in container.iter_inner_content():
            if isinstance(element, Paragraph):
                paragraphs[f"{prefix}p[{p_idx}]"] = element
                p_idx += 1
            elif isinstance(element, Table):
                for r_idx, row in enumerate(element.rows):
                    for c_idx, cell in enumerate(row.cells):
                        path = f"{prefix}table[{t_idx}]/row[{r_idx}]/cell[{c_idx}]"
                        cells[path] = cell
                        walk(cell, path + "/")
                t_idx += 1

    walk(doc)
    by_path: dict[str, list[CandidateAnchor]] = {}
    for anchor in doc_graph.all_anchors:
        path = anchor.element_path.rsplit("/", 1)[0]
        by_path.setdefault(path, []).append(anchor)
    rendered_slots = {}
    for path, anchors in by_path.items():
        target = paragraphs.get(path)
        if target is None:
            target = cells.get(path)
        if target is None:
            raise ValueError(f"Không tìm thấy vị trí dữ liệu trong mẫu: {path}")
        for anchor in sorted(anchors, key=lambda a: a.start_offset, reverse=True):
            field = fields_by_anchor.get(anchor.anchor_id)
            fact = facts_by_field.get(field.field_id) if field else None
            if not fact or fact.status == FactStatus.UNKNOWN or fact.value is None:
                continue
            formatted = _format_value_for_doc(fact.value)
            if (
                fact.status == FactStatus.CONFLICTING
                and anchor.placeholder_type == PlaceholderType.FIXED_TEXT
            ):
                formatted = "[Cần rà soát câu xác nhận ký]"
            element = target._p if isinstance(target, Paragraph) else target._tc
            slot = (element, anchor.start_offset, anchor.end_offset)
            if slot in rendered_slots:
                if rendered_slots[slot] != formatted:
                    raise ValueError("Ô gộp có các giá trị mâu thuẫn, cần duyệt lại ánh xạ mẫu.")
                continue
            rendered_slots[slot] = formatted
            if anchor.placeholder_type == PlaceholderType.EMPTY_CELL:
                target.text = formatted
            elif anchor.placeholder_type in {
                PlaceholderType.DOTTED_LINE,
                PlaceholderType.UNDERLINE,
                PlaceholderType.FIXED_TEXT,
            }:
                if not isinstance(target, Paragraph):
                    raise ValueError("Chỗ trống không thuộc đoạn văn hợp lệ.")
                if "\n" in formatted and anchor.is_multiline:
                    _fill_multiline(
                        target,
                        anchor.placeholder_text,
                        formatted,
                        field.field_id == general_content_field_id,
                    )
                else:
                    _replace_text_in_paragraph(
                        target, anchor.placeholder_text, formatted, anchor.start_offset
                    )
            elif anchor.placeholder_type == PlaceholderType.TEXT_PLACEHOLDER:
                target.add_run(("" if target.text.endswith(" ") else " ") + formatted)

    # Preserve every untouched package part byte-for-byte, including styles,
    # headers, footers, fields, controls, relationships and document metadata.
    from lxml import etree

    body_xml = etree.tostring(doc.element, xml_declaration=True, encoding="UTF-8", standalone=True)
    with zipfile.ZipFile(normalized_docx_path) as original:
        with zipfile.ZipFile(output_docx_path, "w") as completed:
            for info in original.infolist():
                completed.writestr(
                    info,
                    body_xml
                    if info.filename == "word/document.xml"
                    else original.read(info.filename),
                )
    completed_sha = compute_file_sha256(output_docx_path)
    logger.info(
        "Saved completed Word document: %s (SHA-256: %s)", output_docx_path, completed_sha[:12]
    )
    return output_docx_path, completed_sha
