"""Minimal presentation preserving all text and template content."""

from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor


def format_minimal(path: Path) -> dict[str, Any]:
    from meeting_pipeline.minutes.document_formatting import _save_preserving_parts

    document = Document(path)
    original = [p.text for p in document.paragraphs]
    normal = document.styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(12)
    for section in document.sections:
        section.page_width, section.page_height = Mm(210), Mm(297)
        section.top_margin = section.bottom_margin = Mm(20)
        section.left_margin = section.right_margin = Mm(22)
    for paragraph in document.paragraphs:
        paragraph.paragraph_format.line_spacing = 1.15
        paragraph.paragraph_format.space_after = Pt(6)
        paragraph.paragraph_format.widow_control = True
        heading = paragraph.style and (
            paragraph.style.name.startswith("Heading") or paragraph.style.name == "Title"
        )
        for run in paragraph.runs:
            run.font.name = "Arial"
            run.font.size = Pt(14 if heading else 12)
            if heading:
                run.font.color.rgb = RGBColor(0, 0, 0)
                run.font.underline = False
        if heading:
            paragraph.paragraph_format.keep_with_next = True
            paragraph.style.font.color.rgb = RGBColor(0, 0, 0)
            paragraph.style.font.underline = False
            for properties in (paragraph._p.pPr, paragraph.style.element.pPr):
                if properties is not None:
                    for border in list(properties.findall(qn("w:pBdr"))):
                        properties.remove(border)
        else:
            paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    _save_preserving_parts(document, path)
    assert [p.text for p in Document(path).paragraphs] == original
    return {
        "schema_version": "1.0",
        "standard": "minimal",
        "standard_label": "Biên bản tối giản",
        "profile_version": "minimal-v1",
        "source": "local:minimal-v1",
        "status": "checks_passed",
        "checks": {"all_paragraph_text_preserved": True},
        "review_items": [],
        "resolved_metadata": {},
        "two_sided": False,
        "legal_authority_verified": False,
    }
