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
from docx.table import Table
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
    anchor_aliases = {}
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

        for index, match in enumerate(re.finditer(r"\b(?:đã|cùng)\s+ký\b[^.!?;]*", p.text, re.I)):
            if not any(
                a.start_offset < match.end() and a.end_offset > match.start() for a in anchors
            ):
                anchors.append(
                    CandidateAnchor(
                        anchor_id="anc_fixed_"
                        + re.sub(r"[\[\]/]", "_", element_path)
                        + f"_{index}",
                        block_id=f"blk_{order}",
                        element_path=f"{element_path}/fixed[{index}]",
                        start_offset=match.start(),
                        end_offset=match.end(),
                        placeholder_text=match.group(),
                        placeholder_type=PlaceholderType.FIXED_TEXT,
                        nearby_label="Xác nhận ký trong mẫu",
                        section_path=current_section,
                    )
                )

        # Check if this paragraph is a standalone signature block
        upper_text = raw_text.upper()
        if (
            not matches
            and any(sig_kw in upper_text for sig_kw in SIGNATURE_KEYWORDS)
            and ("(KÝ" in upper_text or len(raw_text) < 40)
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

    def process_table(table: Table, table_path: str) -> None:
        nonlocal order, current_section, previous_text
        section, preceding = current_section, previous_text
        visited = {}
        for r_idx, row in enumerate(table.rows):
            for c_idx, cell in enumerate(row.cells):
                cell_path = f"{table_path}/row[{r_idx}]/cell[{c_idx}]"
                if cell._tc in visited:
                    original = visited[cell._tc]
                    old = original.replace("/", "_").replace("[", "_").replace("]", "")
                    new = cell_path.replace("/", "_").replace("[", "_").replace("]", "")
                    for block in blocks:
                        if block.element_path.startswith(original + "/"):
                            for anchor in block.candidate_anchors:
                                anchor_aliases[anchor.anchor_id.replace(old, new, 1)] = (
                                    anchor.anchor_id
                                )
                    continue
                visited[cell._tc] = cell_path
                # Adjacent cells do not inherit each other's headings or labels.
                current_section, previous_text = section, ""
                cell_path = f"{table_path}/row[{r_idx}]/cell[{c_idx}]"
                cell_text = cell.text.strip()
                if (not cell_text or PLACEHOLDER_REGEX.fullmatch(cell_text)) and not cell.tables:
                    anchor = CandidateAnchor(
                        anchor_id=(
                            f"anc_tbl_{table_path[6:-1]}_r_{r_idx}_c_{c_idx}"
                            if re.fullmatch(r"table\[\d+\]", table_path)
                            else "anc_tbl_" + re.sub(r"[\[\]/]", "_", cell_path)
                        ),
                        block_id=f"blk_{order}",
                        element_path=f"{cell_path}/empty_cell",
                        end_offset=len(cell.text),
                        placeholder_text=cell.text or "[empty_cell]",
                        placeholder_type=PlaceholderType.EMPTY_CELL,
                        nearby_label=f"Table {table_path} Row {r_idx} Col {c_idx}",
                        section_path=section,
                    )
                    blocks.append(
                        DocBlock(
                            block_id=f"blk_{order}",
                            order=order,
                            block_type=BlockType.TABLE_CELL,
                            raw_text=cell_text,
                            section_path=section,
                            element_path=cell_path,
                            candidate_anchors=[anchor],
                        )
                    )
                    order += 1
                else:
                    walk(cell, cell_path + "/", BlockType.TABLE_CELL)
        current_section, previous_text = section, preceding

    def walk(container, prefix: str = "", kind: BlockType = BlockType.PARAGRAPH) -> None:
        p_idx = t_idx = 0
        for element in container.iter_inner_content():
            if isinstance(element, Paragraph):
                block = process_paragraph(element, f"{prefix}p[{p_idx}]", kind)
                if block is not None:
                    blocks.append(block)
                p_idx += 1
            else:
                process_table(element, f"{prefix}table[{t_idx}]")
                t_idx += 1

    walk(doc)

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
        anchor_aliases=anchor_aliases,
    )
