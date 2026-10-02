"""Document structure parser and candidate anchor extraction for Word templates.

Analyzes paragraph, table, cell and run hierarchies in OOXML DOCX, detecting
placeholders, blank lines, dotted sequences and signature blocks while strictly
preserving element paths and style boundaries.
Specification: Section 5 (F1) of docs/PLAN_BIEU_MAU_BIEN_BAN_V1.md.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import docx
from docx.text.paragraph import Paragraph

from meeting_pipeline.minutes.converter import compute_file_sha256
from meeting_pipeline.minutes.schemas import (
    BlockType,
    CandidateAnchor,
    DocBlock,
    DocGraph,
    PlaceholderType,
)

logger = logging.getLogger(__name__)

# Regex pattern for dotted runs, underscores, ellipsis (2+ dots/ellipsis, 3+ underscores)
PLACEHOLDER_REGEX = re.compile(r"([…\.]{2,}|_{3,})")

# Section title detection (Roman numerals, numbered sections)
SECTION_HEADING_REGEX = re.compile(r"^(I|II|III|IV|V|VI|VII|VIII|IX|X|\d+)\.\s*(.*)", re.IGNORECASE)

# Common signature markers in Vietnamese official meeting minutes
SIGNATURE_KEYWORDS = {
    "CHỦ TỌA",
    "CHỦ TRÌ",
    "THƯ KÝ",
    "ĐẠI DIỆN",
    "CÁC THÀNH VIÊN KHÁC",
    "NGƯỜI GHI BIÊN BẢN",
    "BÍ THƯ",
}


def _clean_label(raw: str) -> str:
    """Normalize contextual label text around an anchor."""
    cleaned = re.sub(r"[\r\n\t]+", " ", raw).strip()
    # Remove leading numbering or bullets like '1. ', '- '
    cleaned = re.sub(r"^[-*•\d\.\s]+", "", cleaned).strip()
    return cleaned[:120]


def parse_template_document(
    docx_path: Path,
    original_sha256: str | None = None,
    template_id: str | None = None,
) -> DocGraph:
    """Parse a normalized DOCX document into a DocGraph with candidate anchors."""
    if not docx_path.is_file():
        raise FileNotFoundError(f"Document not found: {docx_path}")

    doc = docx.Document(str(docx_path))
    file_sha = compute_file_sha256(docx_path)
    orig_sha = original_sha256 or file_sha
    t_id = template_id or docx_path.stem

    blocks: list[DocBlock] = []
    unmapped_warnings: list[str] = []
    current_section = "Header"
    order = 0
    previous_text = ""

    # 1. Process document body elements in sequential order
    # Helper to process a paragraph
    def process_paragraph(
        p: Paragraph, element_path: str, block_type: BlockType = BlockType.PARAGRAPH
    ) -> DocBlock | None:
        nonlocal current_section, order, previous_text
        raw_text = p.text.strip()
        if not raw_text:
            return None

        # Check section heading
        sec_match = SECTION_HEADING_REGEX.match(raw_text)
        if sec_match:
            current_section = sec_match.group(2).strip() or sec_match.group(1).strip()
            block_type = BlockType.HEADING

        # Find placeholder matches
        matches = list(PLACEHOLDER_REGEX.finditer(p.text))
        anchors: list[CandidateAnchor] = []

        if matches:
            last_end = 0
            for idx, m in enumerate(matches):
                start, end = m.span()
                matched_text = m.group()

                # Extract context label between last match end and current match start
                prefix = p.text[last_end:start].strip()
                last_end = end

                # If prefix is empty or just bullet, look back to previous paragraph text
                if not prefix or prefix in ("-", "\u2013", "•", "*", ":"):
                    nearby_lbl = _clean_label(previous_text) if previous_text else current_section
                else:
                    nearby_lbl = _clean_label(prefix)

                p_type = PlaceholderType.DOTTED_LINE
                if "_" in matched_text:
                    p_type = PlaceholderType.UNDERLINE

                # Check if this placeholder spans multiple lines or whole paragraph
                is_multiline = len(matched_text) > 30 and (
                    len(p.text.strip()) == len(matched_text.strip())
                )

                anchor_id = (
                    f"anc_{element_path.replace('/', '_').replace('[', '_').replace(']', '')}_{idx}"
                )
                anchors.append(
                    CandidateAnchor(
                        anchor_id=anchor_id,
                        block_id=f"blk_{order}",
                        element_path=f"{element_path}/placeholder[{idx}]",
                        start_offset=start,
                        end_offset=end,
                        placeholder_text=matched_text,
                        placeholder_type=p_type,
                        nearby_label=nearby_lbl,
                        section_path=current_section,
                        is_multiline=is_multiline,
                    )
                )

        # Check if this paragraph is an explicit fillable instruction prompt without dots
        # e.g., "- Thông báo tình hình đảng viên...: (ghi cụ thể...)"
        if not anchors and (
            "(ghi " in raw_text.lower()
            or (
                raw_text.endswith(":")
                and len(raw_text) > 15
                and not raw_text.startswith(("I.", "II.", "III.", "IV.", "V.", "1.", "2.", "3."))
            )
        ):
            anchor_id = (
                f"anc_prompt_{element_path.replace('/', '_').replace('[', '_').replace(']', '')}"
            )
            anchors.append(
                CandidateAnchor(
                    anchor_id=anchor_id,
                    block_id=f"blk_{order}",
                    element_path=f"{element_path}/prompt",
                    start_offset=len(p.text),
                    end_offset=len(p.text),
                    placeholder_text="[nội dung cần điền]",
                    placeholder_type=PlaceholderType.TEXT_PLACEHOLDER,
                    nearby_label=_clean_label(raw_text),
                    section_path=current_section,
                    is_multiline=True,
                )
            )

        # Check if this paragraph is a standalone signature block
        upper_text = raw_text.upper()
        if any(sig_kw in upper_text for sig_kw in SIGNATURE_KEYWORDS) and (
            "(KÝ" in upper_text or len(raw_text) < 40
        ):
            anchor_id = (
                f"anc_sig_{element_path.replace('/', '_').replace('[', '_').replace(']', '')}"
            )
            anchors.append(
                CandidateAnchor(
                    anchor_id=anchor_id,
                    block_id=f"blk_{order}",
                    element_path=f"{element_path}/signature",
                    start_offset=0,
                    end_offset=len(p.text),
                    placeholder_text=raw_text,
                    placeholder_type=PlaceholderType.SIGNATURE_BLOCK,
                    nearby_label=raw_text,
                    section_path="Signatures",
                    is_multiline=False,
                )
            )

        block = DocBlock(
            block_id=f"blk_{order}",
            order=order,
            block_type=block_type,
            raw_text=raw_text,
            section_path=current_section,
            element_path=element_path,
            style_name=getattr(p.style, "name", ""),
            candidate_anchors=anchors,
        )
        order += 1
        if not matches and len(raw_text) > 8:
            previous_text = raw_text
        return block

    # Process all body paragraphs
    for p_idx, p in enumerate(doc.paragraphs):
        b = process_paragraph(p, f"p[{p_idx}]")
        if b is not None:
            blocks.append(b)

    # Process all tables
    for t_idx, table in enumerate(doc.tables):
        for r_idx, row in enumerate(table.rows):
            for c_idx, cell in enumerate(row.cells):
                cell_text = cell.text.strip()
                cell_path = f"table[{t_idx}]/row[{r_idx}]/cell[{c_idx}]"

                # Check if cell is completely empty or just dots
                if not cell_text or PLACEHOLDER_REGEX.fullmatch(cell_text):
                    order += 1
                    anc_id = f"anc_tbl_{t_idx}_r_{r_idx}_c_{c_idx}"
                    anc = CandidateAnchor(
                        anchor_id=anc_id,
                        block_id=f"blk_{order}",
                        element_path=f"{cell_path}/empty_cell",
                        start_offset=0,
                        end_offset=len(cell.text),
                        placeholder_text=cell.text or "[empty_cell]",
                        placeholder_type=PlaceholderType.EMPTY_CELL,
                        nearby_label=f"Table {t_idx} Row {r_idx} Col {c_idx}",
                        section_path=current_section,
                    )
                    blocks.append(
                        DocBlock(
                            block_id=f"blk_{order}",
                            order=order,
                            block_type=BlockType.TABLE_CELL,
                            raw_text=cell_text,
                            section_path=current_section,
                            element_path=cell_path,
                            candidate_anchors=[anc],
                        )
                    )
                else:
                    # Check paragraphs inside table cell
                    for p_idx, p in enumerate(cell.paragraphs):
                        b = process_paragraph(
                            p, f"{cell_path}/p[{p_idx}]", block_type=BlockType.TABLE_CELL
                        )
                        if b is not None:
                            blocks.append(b)

    # Check for unmapped warning candidates
    total_anchors = sum(len(b.candidate_anchors) for b in blocks)
    if total_anchors == 0:
        unmapped_warnings.append(
            "Không tìm thấy vị trí placeholder (dòng chấm, ô trống) nào trong tài liệu."
        )

    logger.info(
        "Parsed DocGraph for %s: %d blocks, %d candidate anchors",
        docx_path.name,
        len(blocks),
        total_anchors,
    )

    return DocGraph(
        schema_version="1.0",
        template_id=t_id,
        template_name=docx_path.name,
        original_sha256=orig_sha,
        normalized_docx_sha256=file_sha,
        blocks=blocks,
        unmapped_warnings=unmapped_warnings,
    )
