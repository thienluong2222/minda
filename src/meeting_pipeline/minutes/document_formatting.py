"""Apply Vietnamese administrative/Party presentation to an editable DOCX copy.

Only recognized front matter and meeting signature blocks are rebuilt. Content
paragraphs, detailed headings, tables, images and opaque ZIP parts are retained.
Unknown structures are reported for review rather than silently discarded.
"""

from __future__ import annotations

import io
import re
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Any

import docx
from docx.document import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING, WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Length, Mm, Pt, RGBColor
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph
from lxml import etree

from meeting_pipeline.minutes.format_profiles import PROFILES, DocumentMetadata, FormatProfile
from meeting_pipeline.minutes.renderer import _replace_text_in_paragraph

FONT = "Times New Roman"
LEGAL_HEADERS = ("CỘNG HÒA XÃ HỘI", "CỘNG HOÀ XÃ HỘI", "ĐẢNG CỘNG SẢN VIỆT NAM")
CHAIR = re.compile(r"^(CHỦ TỌA|CHỦ TOẠ|CHỦ TRÌ(?: HỘI NGHỊ)?)$")
SECRETARY = re.compile(r"^(THƯ KÝ|THƯ KÍ|NGƯỜI GHI BIÊN BẢN)$")
PLACEHOLDER = re.compile(r"…|[._]{2,}|TÊN CƠ QUAN|TÊN CẤP ỦY|HỌ VÀ TÊN", re.I)


def _clean(text: str) -> str:
    return " ".join(text.split())


def _mm(length: Length | None) -> float:
    return length.mm if length is not None else 0


def _paragraphs(element: Any, doc: Document) -> list[Paragraph]:
    elements = [element] if element.tag == qn("w:p") else element.xpath(".//w:p")
    return [Paragraph(p, doc) for p in elements]


def _lines(element: Any, doc: Document) -> list[str]:
    return [s.strip() for p in _paragraphs(element, doc) for s in p.text.splitlines() if s.strip()]


def _legal(text: str) -> bool:
    upper = _clean(text).upper()
    return upper.startswith((*LEGAL_HEADERS, "ĐỘC LẬP - TỰ DO - HẠNH PHÚC"))


def _number(text: str) -> bool:
    return bool(re.match(r"^Số\s*[:\d.…_]", text.strip(), re.I))


def _date(text: str) -> bool:
    return bool(re.search(r"ngày.+tháng.+năm", text, re.I))


def _has_value(text: str) -> bool:
    return bool(text.strip()) and not PLACEHOLDER.search(text)


def _content_text(text: str) -> str:
    # Dotted blank slots become editable Word tab leaders, retaining their meaning.
    return re.sub(r"[.…]{12,}|_{8,}|\t", "<BLANK>", text)


def _blank_slots(paragraph: Paragraph, width_mm: float = 165) -> None:
    matches = list(re.finditer(r"[.…]{12,}|_{8,}", paragraph.text))
    for match in reversed(matches):
        _replace_text_in_paragraph(paragraph, match.group(), "\t", match.start())
    if matches:
        paragraph.paragraph_format.tab_stops.add_tab_stop(
            Mm(width_mm - 1), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS
        )


def _font(
    paragraph: Paragraph, size: float, bold: bool | None = None, italic: bool | None = None
) -> None:
    # Include hyperlink/field/content-control runs, which Paragraph.runs omits.
    for element in paragraph._p.xpath(".//w:r"):
        from docx.text.run import Run

        run = Run(element, paragraph)
        run.font.name = FONT
        run.font.size = Pt(size)
        run.font.color.rgb = RGBColor(0, 0, 0)
        fonts = run._r.get_or_add_rPr().get_or_add_rFonts()
        for key in ("ascii", "hAnsi", "eastAsia", "cs"):
            fonts.set(qn(f"w:{key}"), FONT)
        for key in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"):
            fonts.attrib.pop(qn(f"w:{key}"), None)
        if bold is not None:
            run.bold = bold
        if italic is not None:
            run.italic = italic


def _style(paragraph: Paragraph, profile: FormatProfile, role: str, in_table: bool = False) -> None:
    paragraph.style = f"Minutes {role}"
    fmt = paragraph.paragraph_format
    fmt.left_indent = Mm(0)
    fmt.right_indent = Mm(0)
    fmt.first_line_indent = Mm(10 if role == "Body" and not in_table else 0)
    fmt.space_before = Pt(0)
    fmt.space_after = Pt(6 if role in ("Body", "Heading", "Subtitle") else 0)
    fmt.line_spacing = Pt(profile.line_spacing) if profile.exact_spacing else 1.15
    fmt.line_spacing_rule = (
        WD_LINE_SPACING.EXACTLY if profile.exact_spacing else WD_LINE_SPACING.MULTIPLE
    )
    fmt.widow_control = True
    fmt.keep_with_next = role in ("Heading", "Title", "Subtitle", "Header", "Signature Label")
    fmt.keep_together = role != "Body"
    paragraph.alignment = (
        WD_ALIGN_PARAGRAPH.JUSTIFY if role == "Body" else WD_ALIGN_PARAGRAPH.CENTER
    )
    sizes = {
        "Title": profile.title_pt,
        "Subtitle": profile.subtitle_pt,
        "Header": profile.organization_pt,
        "Signature Label": 14,
        "Signature Name": 14,
        "Recipient": 12,
        "Page": 14,
    }
    bold = (
        True
        if role in ("Heading", "Title", "Subtitle", "Signature Label", "Signature Name")
        else None
    )
    _font(
        paragraph,
        sizes.get(role, profile.body_pt),
        bold,
        False
        if role in ("Heading", "Title", "Subtitle", "Signature Label", "Signature Name")
        else None,
    )
    if role in ("Heading", "Title", "Subtitle"):
        for run in paragraph.runs:
            run.underline = False
        border = paragraph._p.get_or_add_pPr().find(qn("w:pBdr"))
        if border is not None:
            border.getparent().remove(border)
    if role == "Recipient":
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        fmt.first_line_indent = Mm(0)
        fmt.line_spacing = 1
        fmt.space_after = Pt(0)


def _styles(doc: Document, profile: FormatProfile) -> None:
    for name in (
        "Body",
        "Heading",
        "Title",
        "Subtitle",
        "Header",
        "Signature Label",
        "Signature Name",
        "Recipient",
        "Page",
        "Rule",
    ):
        key = f"Minutes {name}"
        style = (
            doc.styles[key]
            if key in doc.styles
            else doc.styles.add_style(key, WD_STYLE_TYPE.PARAGRAPH)
        )
        style.font.name = FONT
        style.font.size = Pt(profile.body_pt)
        style.font.color.rgb = RGBColor(0, 0, 0)
    doc.styles["Normal"].font.name = FONT
    doc.styles["Normal"].font.size = Pt(profile.body_pt)


def _border(paragraph: Paragraph, width: float = 12) -> None:
    original_ppr = paragraph._p.get_or_add_pPr()
    old = original_ppr.find(qn("w:pBdr"))
    if old is not None:
        original_ppr.remove(old)
    # Use a separate empty paragraph. Indenting the title paragraph itself
    # shrinks the text area and can wrap the official heading onto two lines.
    element = OxmlElement("w:p")
    paragraph._p.addnext(element)
    rule = Paragraph(element, paragraph._parent)
    rule.style = "Minutes Rule"
    fmt = rule.paragraph_format
    fmt.line_spacing = Pt(1)
    fmt.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    fmt.space_before = Pt(0)
    fmt.space_after = Pt(3)
    fmt.keep_with_next = True
    fmt.first_line_indent = Mm(0)
    ppr = element.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    for key, value in {"val": "single", "sz": "6", "color": "000000", "space": "1"}.items():
        bottom.set(qn(f"w:{key}"), value)
    borders.append(bottom)
    ppr.append(borders)
    # Paragraph borders follow these indents; this keeps the rule under the text.
    fmt.left_indent = Mm(width)
    fmt.right_indent = Mm(width)


def _table_layout(table: Table, width_mm: float, borderless: bool = False) -> None:
    table.autofit = False
    grid = table._tbl.tblGrid.gridCol_lst
    widths = [float(c.w or 1) for c in grid]
    total = sum(widths) or 1
    for col, old in zip(table.columns, widths, strict=True):
        col.width = Mm(width_mm * old / total)
    for row in table.rows:
        # Exact row heights from forms can clip text after font normalization.
        for height in row._tr.xpath("./w:trPr/w:trHeight"):
            height.getparent().remove(height)
        if borderless:
            pr = row._tr.get_or_add_trPr()
            if pr.find(qn("w:cantSplit")) is None:
                pr.append(OxmlElement("w:cantSplit"))
        offset = row.grid_cols_before
        for tc in row._tr.tc_lst:
            span = tc.grid_span
            _Cell(tc, table).width = Mm(width_mm * sum(widths[offset : offset + span]) / total)
            offset += span
    tblw = table._tbl.tblPr.find(qn("w:tblW"))
    if tblw is not None:
        tblw.set(qn("w:type"), "dxa")
        tblw.set(qn("w:w"), str(round(width_mm * 1440 / 25.4)))
    if borderless:
        pr = table._tbl.tblPr
        borders = pr.find(qn("w:tblBorders"))
        if borders is not None:
            pr.remove(borders)
        borders = OxmlElement("w:tblBorders")
        for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
            node = OxmlElement(f"w:{edge}")
            node.set(qn("w:val"), "nil")
            borders.append(node)
        pr.append(borders)


def _document_number(raw: str, abbreviation: str, party: bool) -> str:
    value = re.sub(r"^Số\s*:?\s*", "", raw, flags=re.I).strip()
    match = re.fullmatch(r"(\d+)(?:/BB-|-BB/)([^\s]+)", value, re.I)
    if match:
        value, abbreviation = match.groups()
    if not value or PLACEHOLDER.search(value):
        value = "…"
    if value.isdigit() or value == "…":
        value = value.zfill(2) if value.isdigit() else value
        value = (
            f"{value}-BB/{abbreviation or '…'}" if party else f"{value}/BB-{abbreviation or '…'}"
        )
    return f"Số {value}" if party else f"Số: {value}"


def _front_matter(
    doc: Document, metadata: DocumentMetadata, profile: FormatProfile, issues: list[dict[str, str]]
) -> tuple[Paragraph, set[Any], dict[str, str]]:
    title = next((p for p in doc.paragraphs if _clean(p.text).upper().startswith("BIÊN BẢN")), None)
    if title is None:
        title = doc.add_paragraph("BIÊN BẢN")
        doc.element.body.insert(0, title._p)
        issues.append(
            {
                "code": "title_missing",
                "message": "Mẫu chưa có tên biên bản rõ ràng; đã thêm BIÊN BẢN, "
                "cần kiểm tra tên cuộc họp.",
            }
        )
    remove: list[Any] = []
    organization: list[str] = []
    raw_number = ""
    raw_date = ""
    for element in list(doc.element.body):
        if element is title._p:
            break
        lines = _lines(element, doc)
        if element.tag == qn("w:tbl") and any(_legal(s) for s in lines):
            table = Table(element, doc)
            if len(table.rows) == 1 and len(table.rows[0].cells) == 2:
                left, right = table.rows[0].cells
                if any(_legal(s) for s in right.text.splitlines()):
                    organization.extend(
                        s
                        for s in left.text.splitlines()
                        if s.strip() and s.strip() != "*" and not _number(s)
                    )
                    raw_number = next((s for s in lines if _number(s)), raw_number)
                    raw_date = next((s for s in lines if _date(s)), raw_date)
                    if all(
                        _legal(s) or _date(s) or s == "*"
                        for s in right.text.splitlines()
                        if s.strip()
                    ):
                        remove.append(element)
                        continue
            issues.append(
                {
                    "code": "complex_front_matter",
                    "message": "Khối đầu văn bản có cấu trúc phức tạp; "
                    "cần đối chiếu bố cục và thông tin được giữ lại.",
                }
            )
        elif element.tag == qn("w:p") and not lines:
            if not element.xpath(".//w:drawing | .//w:pict | .//w:fldChar"):
                remove.append(element)
        elif element.tag == qn("w:p") and lines:
            text = " ".join(lines)
            if _legal(text) or text == "*":
                if all(_legal(line) or line == "*" for line in lines):
                    remove.append(element)
                else:
                    issues.append(
                        {
                            "code": "mixed_front_matter",
                            "message": "Phần đầu có thông tin bổ sung cùng đoạn tiêu đề; "
                            "đã giữ lại để đối chiếu và sắp xếp.",
                        }
                    )
            elif _number(text):
                raw_number = text
                remove.append(element)
            elif _date(text):
                raw_date = text
                remove.append(element)
            elif text.isupper() and len(text) < 200 and not re.match(r"^[\dIVX]+[.)]", text):
                organization.append(text)
                remove.append(element)
    party = profile.standard == "hd05_2026"
    org = metadata.organization or (organization[-1].strip() if organization else "")
    parent = metadata.parent_organization or "\n".join(s.strip() for s in organization[:-1])
    for key, value in (
        ("organization", org),
        ("document_number", metadata.document_number or raw_number),
    ):
        if not _has_value(value):
            issues.append(
                {
                    "code": f"{key}_missing",
                    "message": {
                        "organization": "Cần bổ sung tên cơ quan ban hành.",
                        "document_number": "Cần bổ sung số và ký hiệu văn bản từ sổ văn thư.",
                    }[key],
                }
            )
    if metadata.issue_date:
        d = metadata.issue_date
        month = str(d.month).zfill(2) if d.month < 3 else str(d.month)
        raw_date = f"{metadata.issue_place or '…'}, ngày {d.day:02d} tháng {month} năm {d.year}"
        if not metadata.issue_place:
            issues.append(
                {"code": "issue_place_missing", "message": "Cần bổ sung địa danh ban hành."}
            )
    elif metadata.issue_place:
        raw_date = f"{metadata.issue_place}, ngày … tháng … năm …"
    if party and (not raw_date or not _has_value(raw_date)):
        issues.append(
            {
                "code": "issue_date_missing",
                "message": "Cần kiểm tra địa danh và ngày ban hành; ngày họp được quản lý riêng.",
            }
        )
    safe_remove = []
    for element in remove:
        if element.xpath(".//w:drawing | .//w:pict | .//w:object"):
            issues.append(
                {
                    "code": "front_matter_object",
                    "message": "Phần đầu có ảnh hoặc đối tượng; đã giữ lại để đối chiếu.",
                }
            )
        else:
            safe_remove.append(element)
    remove = safe_remove
    changed = {p._p for element in remove for p in _paragraphs(element, doc)}
    for element in remove:
        element.getparent().remove(element)
    table = doc.add_table(rows=1, cols=2)
    title._p.addprevious(table._tbl)
    table.columns[0].width, table.columns[1].width = Mm(60), Mm(105)
    left, right = table.rows[0].cells
    organization_text = (parent + "\n" if parent else "") + (
        org or ("TÊN CẤP ỦY, TỔ CHỨC ĐẢNG" if party else "TÊN CƠ QUAN, TỔ CHỨC")
    )
    for i, line in enumerate(organization_text.splitlines()):
        p = left.paragraphs[0] if i == 0 else left.add_paragraph()
        p.text = line
    for i, p in enumerate(left.paragraphs):
        _style(p, profile, "Header", True)
        _font(p, profile.organization_pt, i == len(left.paragraphs) - 1, False)
        for run in p.runs:
            run.font.all_caps = True
    if party:
        _style(left.add_paragraph("*"), profile, "Header", True)
    else:
        _border(left.paragraphs[-1], 17)
    num = left.add_paragraph(
        _document_number(
            metadata.document_number or raw_number, metadata.organization_abbreviation, party
        )
    )
    _style(num, profile, "Header", True)
    _font(num, profile.number_pt, False, False)
    if not _has_value(num.text) and not any(i["code"] == "document_number_missing" for i in issues):
        issues.append(
            {
                "code": "document_number_missing",
                "message": "Cần bổ sung đầy đủ số và ký hiệu cơ quan trong số văn bản.",
            }
        )
    expected_number = r"Số (?:\d+|…)-BB/[^\s]+" if party else r"Số: (?:\d+|…)/BB-[^\s]+"
    if not re.fullmatch(expected_number, num.text):
        issues.append(
            {
                "code": "document_number_format",
                "message": "Cần kiểm tra số/ký hiệu biên bản BB và chữ viết tắt cơ quan.",
            }
        )
    if party:
        right.text = "ĐẢNG CỘNG SẢN VIỆT NAM"
        _style(right.paragraphs[0], profile, "Header", True)
        _font(right.paragraphs[0], 15, True, False)
        # TNR Bold 15 pt title width is 72.9 mm; cell text area is 101.2 mm.
        _border(right.paragraphs[0], 14.15)
    else:
        right.text = "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM"
        _style(right.paragraphs[0], profile, "Header", True)
        _font(right.paragraphs[0], 13, True, False)
        p = right.add_paragraph("Độc lập - Tự do - Hạnh phúc")
        _style(p, profile, "Header", True)
        _font(p, 14, True, False)
        # TNR Bold 14 pt motto width is 60.5 mm.
        _border(p, 20.35)
    if party or raw_date:
        p = right.add_paragraph(raw_date or "…, ngày … tháng … năm …")
        _style(p, profile, "Header", True)
        _font(p, 14, False, True)
        p.paragraph_format.space_before = Pt(6)
    _table_layout(table, 165, True)
    return (
        title,
        changed,
        {
            "organization": org,
            "parent_organization": parent,
            "document_number": num.text,
            "issue_date_place": raw_date,
        },
    )


def _signatures(
    doc: Document,
    metadata: DocumentMetadata,
    profile: FormatProfile,
    issues: list[dict[str, str]],
    grounded_people: dict[str, str],
) -> set[Any]:
    party = profile.standard == "hd05_2026"
    old = None
    columns: dict[str, int] = {}
    for table in doc.tables:
        if len(table.rows[0].cells) != 2:
            continue
        found = {}
        for i, cell in enumerate(table.rows[0].cells):
            for line in cell.text.splitlines():
                if CHAIR.fullmatch(_clean(line).upper()):
                    found["chair"] = i
                if SECRETARY.fullmatch(_clean(line).upper()):
                    found["secretary"] = i
        if len(found) == 2 and found["chair"] != found["secretary"]:
            old, columns = table, found
    changed: set[Any] = set()
    # Non-meeting forms (handover etc.) have their own signatories; preserve them.
    other_signatures = any(
        "ĐẠI DIỆN BÊN" in c.text.upper() for t in doc.tables for r in t.rows for c in r.cells
    )
    if old is None and other_signatures:
        issues.append(
            {
                "code": "specialized_signatures",
                "message": "Mẫu có người ký chuyên biệt; "
                "cần kiểm tra thể thức phù hợp với loại biên bản.",
            }
        )
        return changed
    table = doc.add_table(rows=1, cols=2)
    paragraph_sources: dict[str, list[Any]] = {}
    if old is not None:
        old._tbl.addprevious(table._tbl)
    else:
        # Move a recognized trailing pair of plain paragraph labels into cells.
        labels = [
            p
            for p in doc.paragraphs
            if CHAIR.fullmatch(_clean(p.text).upper())
            or SECRETARY.fullmatch(_clean(p.text).upper())
        ]
        if labels:
            labels[0]._p.addprevious(table._tbl)
            for p in labels:
                role = "chair" if CHAIR.fullmatch(_clean(p.text).upper()) else "secretary"
                source = [p._p]
                following = p._p.getnext()
                while following is not None and following.tag == qn("w:p"):
                    text = Paragraph(following, doc).text.strip()
                    if text and not text.startswith("(") and text not in grounded_people.values():
                        break
                    source.append(following)
                    following = following.getnext()
                paragraph_sources[role] = [deepcopy(e) for e in source]
                for element in source:
                    changed.add(element)
                    element.getparent().remove(element)
    for idx, role in enumerate(("secretary", "chair")):
        cell = table.rows[0].cells[idx]
        supplied_name = metadata.secretary if role == "secretary" else metadata.chairperson
        label = (
            ("NGƯỜI GHI BIÊN BẢN" if party else "THƯ KÝ")
            if role == "secretary"
            else ("CHỦ TRÌ HỘI NGHỊ" if party else "CHỦ TỌA")
        )
        if old is not None:
            for child in list(cell._tc):
                if child.tag != qn("w:tcPr"):
                    cell._tc.remove(child)
            for row in old.rows:
                for child in row.cells[columns[role]]._tc:
                    if child.tag != qn("w:tcPr"):
                        cell._tc.append(deepcopy(child))
            changed.update(p._p for p in _paragraphs(old._tbl, doc))
        elif role in paragraph_sources:
            for child in list(cell._tc):
                if child.tag != qn("w:tcPr"):
                    cell._tc.remove(child)
            for child in paragraph_sources[role]:
                cell._tc.append(child)
        if not cell.paragraphs:
            cell.add_paragraph()
        for empty in cell.paragraphs[1:]:
            if not empty.text.strip() and not empty._p.xpath(".//w:drawing | .//w:pict"):
                empty._p.getparent().remove(empty._p)
        # A signature label is a presentation component, not a content heading.
        p = cell.paragraphs[0]
        p.text = label
        _style(p, profile, "Signature Label", True)
        names = [
            p
            for p in cell.paragraphs[1:]
            if _has_value(p.text) and not p.text.strip().startswith("(")
        ]
        if supplied_name:
            if len(names) == 1:
                names[0].text = supplied_name
            else:
                names = [cell.add_paragraph(supplied_name)]
        elif not names:
            marker = (
                r"(?:Chủ tọa|Chủ toạ|Chủ trì)"
                if role == "chair"
                else r"(?:Thư ký|Thư kí|Người ghi biên bản)"
            )
            candidates = []
            for paragraph in doc.paragraphs:
                match = re.match(rf"^{marker}(?:\s*\([^)]*\))?\s*:\s*(.+)$", paragraph.text, re.I)
                if match and _has_value(match.group(1)):
                    candidates.append(match.group(1).strip())
            if len(set(candidates)) == 1:
                names = [cell.add_paragraph(candidates[0])]
            elif role in grounded_people:
                names = [cell.add_paragraph(grounded_people[role])]
        if not names:
            issues.append(
                {
                    "code": f"{role}_missing",
                    "message": "Cần bổ sung họ tên "
                    + ("người ghi biên bản." if role == "secretary" else "người chủ trì."),
                }
            )
            cell.add_paragraph("…")
        # Reserve handwriting space without inserting fake signatures or stamps.
        p.paragraph_format.space_after = Pt(42)
        name_elements = {p._p for p in names}
        for p in cell.paragraphs[1:]:
            _style(p, profile, "Signature Name" if p._p in name_elements else "Header", True)
    if old is not None:
        old._tbl.getparent().remove(old._tbl)
    _table_layout(table, 165, True)
    if party:
        if metadata.party_signature == "review":
            issues.append(
                {
                    "code": "party_signature_authority",
                    "message": "Cần xác định chủ trì được ký trực tiếp hay phải có "
                    "xác nhận chữ ký theo Hướng dẫn 05.",
                }
            )
        elif metadata.party_signature == "confirmation":
            cell = table.rows[0].cells[1]
            for text in (
                "Xác nhận chữ ký của đồng chí " + (metadata.chairperson or "…"),
                metadata.confirmer_position or "T/L …\nCHÁNH VĂN PHÒNG (hoặc PHÓ CHÁNH VĂN PHÒNG)",
                metadata.confirmer_name or "…",
            ):
                for line in text.splitlines():
                    p = cell.add_paragraph(line)
                    _style(p, profile, "Signature Label" if line.isupper() else "Header", True)
            if not metadata.confirmer_position or not metadata.confirmer_name:
                issues.append(
                    {
                        "code": "confirmer_missing",
                        "message": "Cần bổ sung quyền hạn, chức vụ "
                        "và họ tên người xác nhận chữ ký.",
                    }
                )
    return changed


def _recipients(doc: Document, metadata: DocumentMetadata) -> set[Any]:
    if not metadata.recipients:
        return set()
    label = next(
        (p for p in doc.paragraphs if re.match(r"^Nơi nhận\s*:", p.text.strip(), re.I)), None
    )
    changed = set()
    if label is None:
        label = doc.add_paragraph("Nơi nhận:")
    else:
        following = label._p.getnext()
        while following is not None and following.tag == qn("w:p"):
            p = Paragraph(following, doc)
            if p.text.strip() and not re.match(r"^(?:[-\u2013•]|Lưu\s*:)", p.text.strip(), re.I):
                break
            changed.add(following)
            next_element = following.getnext()
            following.getparent().remove(following)
            following = next_element
    previous = label._p
    for line in metadata.recipients.splitlines():
        p = doc.add_paragraph(line)
        previous.addnext(p._p)
        previous = p._p
    return changed


def _strip_page_fields(paragraph: Paragraph) -> None:
    for field in paragraph._p.xpath('.//w:fldSimple[contains(@w:instr, "PAGE")]'):
        field.getparent().remove(field)
    pending: list[Any] = []
    is_page = False
    for run in paragraph._p.xpath(".//w:r"):
        if run.xpath('./w:fldChar[@w:fldCharType="begin"]'):
            pending = [run]
            is_page = False
        elif pending:
            pending.append(run)
        if pending and run.xpath('.//w:instrText[contains(text(), "PAGE")]'):
            is_page = True
        if pending and run.xpath('./w:fldChar[@w:fldCharType="end"]'):
            if is_page:
                for node in pending:
                    node.getparent().remove(node)
            pending = []


def _pagination(
    doc: Document, profile: FormatProfile, two_sided: bool, issues: list[dict[str, str]]
) -> None:
    settings = doc.settings.element
    for old in settings.findall(qn("w:mirrorMargins")):
        settings.remove(old)
    if two_sided:
        settings.append(OxmlElement("w:mirrorMargins"))
    seen = set()
    for i, section in enumerate(doc.sections):
        landscape = _mm(section.page_width) > _mm(section.page_height)
        section.page_width, section.page_height = (
            (Mm(297), Mm(210)) if landscape else (Mm(210), Mm(297))
        )
        section.top_margin = section.bottom_margin = Mm(20)
        section.left_margin, section.right_margin = Mm(30), Mm(15)
        section.gutter = Mm(0)
        section.header_distance = Mm(10)
        section.different_first_page_header_footer = i == 0
        pgnum = section._sectPr.find(qn("w:pgNumType"))
        if pgnum is not None:
            section._sectPr.remove(pgnum)
        if i == 0:
            pgnum = OxmlElement("w:pgNumType")
            pgnum.set(qn("w:start"), "1")
            section._sectPr.append(pgnum)
        for container in (
            section.header,
            section.first_page_header,
            section.even_page_header,
            section.footer,
            section.first_page_footer,
            section.even_page_footer,
        ):
            if container.part.partname in seen:
                continue
            seen.add(container.part.partname)
            for p in _paragraphs(container._element, doc):
                _strip_page_fields(p)
                removable = (
                    _legal(p.text) and all(_legal(s) for s in p.text.splitlines() if s.strip())
                ) or re.fullmatch(r"(?:Trang\s*)?[\d\s/]*", p.text.strip(), re.I)
                if removable and not p._p.xpath(".//w:drawing | .//w:pict | .//w:object"):
                    p._p.getparent().remove(p._p)
                else:
                    _font(p, profile.body_pt)
                    if p.text.strip() and not any(
                        i["code"] == "retained_header_footer" for i in issues
                    ):
                        issues.append(
                            {
                                "code": "retained_header_footer",
                                "message": "Đầu/cuối trang có nội dung bổ sung được giữ lại; "
                                "cần đối chiếu vị trí và cách trình bày.",
                            }
                        )
        # Reusing linked headers produces one PAGE field across continuous sections.
        for header in (section.header, section.even_page_header):
            if not header._element.xpath('.//w:fldSimple[@w:instr="PAGE"]'):
                empty_paragraph = next(
                    (p for p in header.paragraphs if not p.text and not p.runs), None
                )
                p = empty_paragraph if empty_paragraph is not None else header.add_paragraph()
                _style(p, profile, "Page", True)
                p.paragraph_format.line_spacing = 1
                p.paragraph_format.space_after = Pt(0)
                field = OxmlElement("w:fldSimple")
                field.set(qn("w:instr"), "PAGE")
                run = OxmlElement("w:r")
                text = OxmlElement("w:t")
                text.text = "2"
                run.append(text)
                field.append(run)
                p._p.append(field)
                _font(p, 14, False, False)


def _save_preserving_parts(doc: Document, path: Path) -> None:
    stream = io.BytesIO()
    doc.save(stream)
    with zipfile.ZipFile(path) as original, zipfile.ZipFile(stream) as edited:
        parts = {n: original.read(n) for n in original.namelist()}
        for name in edited.namelist():
            if (
                name not in parts
                or name in ("word/document.xml", "word/styles.xml", "word/settings.xml")
                or re.fullmatch(r"word/(?:header|footer)\d+\.xml", name)
            ):
                parts[name] = edited.read(name)
            elif name in ("[Content_Types].xml", "word/_rels/document.xml.rels"):
                # Preserve unknown extension relationships/content types too.
                root, updated = etree.fromstring(parts[name]), etree.fromstring(edited.read(name))
                key = "Id" if name.endswith(".rels") else "PartName"
                existing = {(c.tag, c.get(key) or c.get("Extension")): c for c in root}
                for child in updated:
                    ident = (child.tag, child.get(key) or child.get("Extension"))
                    if ident in existing:
                        root.replace(existing[ident], child)
                    else:
                        root.append(child)
                parts[name] = etree.tostring(
                    root, xml_declaration=True, encoding="UTF-8", standalone=True
                )
    temporary = path.with_suffix(".formatting.docx")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as output:
        for name, data in parts.items():
            output.writestr(name, data)
    temporary.replace(path)


def format_minutes_document(
    path: Path,
    standard: str,
    metadata: DocumentMetadata | None = None,
    two_sided: bool = False,
    grounded_people: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Format a filled copy and return verifiable checks plus human review items."""
    if standard == "minimal":
        from meeting_pipeline.minutes.minimal_format import format_minimal

        if two_sided:
            raise ValueError("Chế độ tối giản hiện dùng bố cục một mặt.")
        return format_minimal(path)
    profile = PROFILES[standard]
    metadata = metadata or DocumentMetadata()
    if two_sided and standard != "hd05_2026":
        raise ValueError("Lề in hai mặt hiện áp dụng cho thể thức Đảng theo Hướng dẫn 05.")
    doc = docx.Document(str(path))
    issues: list[dict[str, str]] = []
    if any(_mm(s.page_width) > _mm(s.page_height) for s in doc.sections):
        issues.append(
            {
                "code": "landscape_tables",
                "message": "Mẫu có trang ngang; cần đối chiếu rằng các trang này "
                "dùng cho bảng/biểu và kiểm tra bề rộng bảng.",
            }
        )
    before = [(p._p, p.text) for p in _paragraphs(doc.element.body, doc)]
    _styles(doc, profile)
    for p in doc.paragraphs:
        if p.style is not None and p.style.name == "Minutes Rule" and not p.text:
            p._p.getparent().remove(p._p)
    title, changed, resolved = _front_matter(doc, metadata, profile, issues)
    title_index = next(i for i, p in enumerate(doc.paragraphs) if p._p is title._p)
    for p in doc.paragraphs[title_index + 1 : title_index + 5]:
        if p.text.strip() == "-----":
            changed.add(p._p)
            p._p.getparent().remove(p._p)
    changed.update(_signatures(doc, metadata, profile, issues, grounded_people or {}))
    changed.update(_recipients(doc, metadata))
    protected = [text for element, text in before if element not in changed and text.strip()]
    if doc.element.body.xpath(".//w:txbxContent | .//w:altChunk | .//w:object"):
        issues.append(
            {
                "code": "embedded_content",
                "message": "Mẫu có hộp văn bản hoặc đối tượng nhúng; "
                "cần đối chiếu trực quan các đối tượng này.",
            }
        )
    if any("PHỤ LỤC" in p.text.upper() for p in doc.paragraphs):
        issues.append(
            {
                "code": "appendix_pagination",
                "message": "Cần kiểm tra việc đánh số trang riêng cho từng phụ lục.",
            }
        )
    if doc.paragraphs and re.fullmatch(r"\d{1,4}", doc.paragraphs[-1].text.strip()):
        issues.append(
            {
                "code": "possible_body_page_number",
                "message": "Mẫu có một dòng số ở cuối nội dung; cần kiểm tra số trang gõ tay.",
            }
        )
    recipient = False
    after_title = False
    for p in doc.paragraphs:
        _blank_slots(p)
        if p._p is title._p:
            _style(p, profile, "Title")
            for run in p.runs:
                run.font.all_caps = True
            p.paragraph_format.space_before = Pt(12)
            p.paragraph_format.space_after = Pt(6)
            after_title = True
        elif re.match(r"^Nơi nhận\s*:", p.text.strip(), re.I):
            recipient = True
            _style(p, profile, "Recipient")
            _font(
                p,
                14 if standard == "hd05_2026" else 12,
                standard == "nd30_2020",
                standard == "nd30_2020",
            )
            if standard == "hd05_2026":
                for run in p.runs:
                    run.underline = True
        elif recipient:
            _style(p, profile, "Recipient")
        elif (
            after_title
            and (
                title.text.strip().upper() == "BIÊN BẢN"
                or re.match(r"^(Về việc|V/v|Tháng|Hội nghị|Cuộc họp)\b", p.text.strip(), re.I)
            )
            and p.text.strip()
            and not re.match(r"^(?:[IVX]+[.)]|\d+[.)])\s", p.text.strip())
            and not re.match(
                r"^(Thời gian|Địa điểm|Hôm nay|Thành phần|Chủ trì|Nội dung)\b", p.text.strip(), re.I
            )
        ):
            _style(p, profile, "Subtitle")
            if standard == "hd05_2026":
                separator = doc.add_paragraph("-----")
                p._p.addnext(separator._p)
                _style(separator, profile, "Header")
            else:
                _border(p, 64.5)
            after_title = False
        else:
            after_title = False
            heading = (
                bool(re.match(r"^(?:[IVX]+[.)]|\d+(?:\.\d+)*[.)])\s", p.text.strip()))
                and len(p.text) < 250
            )
            heading = (
                heading
                or (p.style is not None and p.style.name.startswith("Heading"))
                or bool(p._p.xpath("./w:pPr/w:outlineLvl"))
                or p.text.strip().upper() == "NỘI DUNG CUỘC HỌP"
            )
            _style(p, profile, "Heading" if heading else "Body")
            if heading:
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    if not any(re.match(r"^Nơi nhận\s*:", p.text.strip(), re.I) for p in doc.paragraphs):
        issues.append(
            {
                "code": "recipients_missing",
                "message": "Cần kiểm tra và bổ sung nơi nhận khi phát hành văn bản.",
            }
        )
    for table in doc.tables:
        role_table = any(
            p.style.name in ("Minutes Header", "Minutes Signature Label")
            for r in table.rows
            for c in r.cells
            for p in c.paragraphs
        )
        if role_table:
            continue
        _table_layout(table, 165)
        for p in _paragraphs(table._tbl, doc):
            # Cell width is used rather than the full page for tab leaders.
            tc = p._p.getparent()
            width = _Cell(tc, table).width.mm - 4 if tc.tag == qn("w:tc") else 161
            _blank_slots(p, width)
            _style(p, profile, "Body", True)
    _pagination(doc, profile, two_sided, issues)
    _save_preserving_parts(doc, path)
    reopened = docx.Document(str(path))
    all_texts = [p.text for p in _paragraphs(reopened.element.body, reopened)]
    body_paragraphs = [
        p
        for p in _paragraphs(reopened.element.body, reopened)
        if p.style is not None and p.style.name == "Minutes Body"
    ]
    cursor = iter(_content_text(text) for text in all_texts)
    preserved = all(
        any(_content_text(text) == candidate for candidate in cursor) for text in protected
    )
    checks = {
        "protected_content_and_heading_order": preserved,
        "a4_sections": all(
            sorted((round(_mm(s.page_width)), round(_mm(s.page_height)))) == [210, 297]
            for s in reopened.sections
        ),
        "margins": all(
            (
                round(_mm(s.top_margin)),
                round(_mm(s.bottom_margin)),
                round(_mm(s.left_margin)),
                round(_mm(s.right_margin)),
            )
            == (20, 20, 30, 15)
            for s in reopened.sections
        ),
        "first_page_number_hidden": reopened.sections[0].different_first_page_header_footer,
        "editable_page_field": bool(
            reopened.sections[0].header._element.xpath('.//w:fldSimple[@w:instr="PAGE"]')
        ),
        "body_font_and_size": all(
            all(r.font.name == FONT and r.font.size == Pt(14) for r in p.runs)
            for p in body_paragraphs
        ),
        "body_spacing_and_alignment": all(
            p.alignment == WD_ALIGN_PARAGRAPH.JUSTIFY
            and p.paragraph_format.space_after >= Pt(6)
            and (
                p.paragraph_format.line_spacing == Pt(20)
                if profile.exact_spacing
                else abs(p.paragraph_format.line_spacing - 1.15) < 0.01
            )
            for p in body_paragraphs
        ),
    }
    if not all(checks.values()):
        raise ValueError(
            "Kiểm tra DOCX sau định dạng thất bại: "
            + ", ".join(k for k, v in checks.items() if not v)
        )
    return {
        "schema_version": "1.0",
        "standard": standard,
        "standard_label": profile.label,
        "profile_version": "2026-10-15.1",
        "source": profile.source,
        "status": "needs_review" if issues else "checks_passed",
        "checks": checks,
        "review_items": issues,
        "resolved_metadata": resolved,
        "two_sided": two_sided,
        "protected_paragraphs": len(protected),
        "visual_review": "required",
        "legal_authority_verified": False,
    }
