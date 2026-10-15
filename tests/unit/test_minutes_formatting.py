"""Presentation, content retention and service persistence gates for both standards."""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path

import docx
import pytest
from docx.enum.section import WD_SECTION_START
from docx.enum.text import WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm

from meeting_pipeline.minutes.converter import compute_file_sha256, normalize_template
from meeting_pipeline.minutes.doc_parser import parse_template_document
from meeting_pipeline.minutes.document_formatting import format_minutes_document
from meeting_pipeline.minutes.format_profiles import DocumentMetadata
from meeting_pipeline.minutes.renderer import render_completed_document
from meeting_pipeline.minutes.schema_mapper import M0RuleSchemaMapper
from meeting_pipeline.minutes.schemas import FactStatus, MeetingFact
from meeting_pipeline.minutes.service import MinutesService
from meeting_pipeline.minutes.text_engine import MinutesOptions

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/templates"


def metadata() -> DocumentMetadata:
    return DocumentMetadata(
        parent_organization="ĐẢNG BỘ CƠ QUAN A",
        organization="CHI BỘ PHÒNG TỔNG HỢP",
        organization_abbreviation="CB",
        document_number="07",
        issue_place="Hà Nội",
        issue_date="2026-10-15",
        chairperson="Nguyễn Văn A",
        secretary="Trần Thị B",
        recipients="- Các thành viên;\n- Lưu: Hồ sơ.",
        party_signature="direct",
    )


@pytest.mark.parametrize("standard", ["nd30_2020", "hd05_2026"])
@pytest.mark.parametrize("mode", ["detailed", "general"])
@pytest.mark.parametrize("filename", ["mau_bien_ban_hop_chung.doc", "bien_ban_hop_chi_bo.docx"])
def test_eight_word_format_combinations(
    tmp_path: Path, standard: str, mode: str, filename: str
) -> None:
    original = FIXTURES / filename
    original_hash = compute_file_sha256(original)
    converted = normalize_template(original, tmp_path / "template")
    graph = parse_template_document(converted.normalized_docx_path)
    schema = M0RuleSchemaMapper().propose_schema(graph)
    # Select a real multiline slot so the same formatter sees native general headings.
    anchor = next(a for a in graph.all_anchors if a.is_multiline)
    field = next(f for f in schema.fields if f.anchor_id == anchor.anchor_id)
    body = (
        "1. Tiến độ triển khai\nLan đề xuất thử nghiệm; chưa thống nhất thời hạn.\n"
        "2. Công việc tiếp theo\nHuy kiểm tra 20 tài liệu."
    )
    out = tmp_path / "completed.docx"
    render_completed_document(
        converted.normalized_docx_path,
        out,
        graph,
        schema,
        [MeetingFact(field_id=field.field_id, value=body, status=FactStatus.SUPPORTED)],
        general_content_field_id=field.field_id if mode == "general" else None,
    )
    filled = docx.Document(out)
    original_headings = [
        p.text for p in filled.paragraphs if p.text.startswith(("1.", "2.", "I.", "II."))
    ]
    report = format_minutes_document(out, standard, metadata(), two_sided=standard == "hd05_2026")
    final = docx.Document(out)
    text = " ".join(final.element.body.xpath(".//w:t/text()"))
    assert "Lan đề xuất thử nghiệm; chưa thống nhất thời hạn." in text
    assert "Huy kiểm tra 20 tài liệu." in text

    def canonical(s: str) -> str:
        return re.sub(r"[.…]{12,}|_{8,}|\t", "<BLANK>", s)

    assert all(
        canonical(h) in [canonical(p.text) for p in final.paragraphs] for h in original_headings
    )
    assert all(report["checks"].values())
    assert compute_file_sha256(original) == original_hash
    assert final.sections[0].page_width.mm == pytest.approx(210, abs=0.05)
    assert final.sections[0].left_margin.mm == pytest.approx(30, abs=0.05)
    paragraph = next(p for p in final.paragraphs if "Lan đề xuất" in p.text)
    assert paragraph.runs[0].font.name == "Times New Roman"
    assert paragraph.runs[0].font.size.pt == 14
    if standard == "hd05_2026":
        assert paragraph.paragraph_format.line_spacing_rule == WD_LINE_SPACING.EXACTLY
        assert paragraph.paragraph_format.line_spacing.pt == 20
        assert "ĐẢNG CỘNG SẢN VIỆT NAM" in text
        assert "CỘNG HÒA XÃ HỘI" not in text
        assert "Số 07-BB/CB" in text
        assert final.settings.element.find(qn("w:mirrorMargins")) is not None
    else:
        assert paragraph.paragraph_format.line_spacing == pytest.approx(1.15)
        assert "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM" in text
        assert "ĐẢNG CỘNG SẢN VIỆT NAM" not in text
        assert "Số: 07/BB-CB" in text
    signatures = final.tables[-1]
    assert "Trần Thị B" in signatures.cell(0, 0).text
    assert "Nguyễn Văn A" in signatures.cell(0, 1).text


def test_unknown_metadata_is_explicit_and_long_blanks_are_editable(tmp_path: Path) -> None:
    path = tmp_path / "unknown.docx"
    d = docx.Document()
    d.add_paragraph("BIÊN BẢN")
    d.add_paragraph("Thời gian: " + "." * 140)
    d.add_paragraph("I. Nội dung chi tiết")
    d.add_paragraph("Chưa quyết định thời hạn.")
    d.save(path)
    report = format_minutes_document(path, "hd05_2026")
    assert report["status"] == "needs_review"
    codes = {i["code"] for i in report["review_items"]}
    assert {
        "organization_missing",
        "document_number_missing",
        "issue_date_missing",
        "chair_missing",
        "secretary_missing",
        "party_signature_authority",
    } <= codes
    d = docx.Document(path)
    p = next(p for p in d.paragraphs if p.text.startswith("Thời gian:"))
    assert "\t" in p.text
    assert p._p.xpath('./w:pPr/w:tabs/w:tab[@w:leader="dot"]')
    assert "Chưa quyết định thời hạn." in [p.text for p in d.paragraphs]


def test_tables_sections_and_opaque_parts_survive(tmp_path: Path) -> None:
    path = tmp_path / "complex.docx"
    d = docx.Document()
    d.add_paragraph("BIÊN BẢN")
    d.add_paragraph("I. Bảng đánh giá")
    table = d.add_table(rows=2, cols=3)
    table.cell(0, 0).merge(table.cell(0, 1)).text = "Hai cột được gộp"
    table.cell(1, 2).text = "Nội dung quan trọng 25%"
    section = d.add_section(WD_SECTION_START.NEW_PAGE)
    section.page_width, section.page_height = Mm(297), Mm(210)
    d.add_paragraph("II. Kết luận riêng")
    d.save(path)
    with zipfile.ZipFile(path, "a") as z:
        z.writestr("customXml/unrelated.bin", b"\x00opaque-part\xff")
    report = format_minutes_document(path, "nd30_2020", metadata())
    assert report["checks"]["protected_content_and_heading_order"]
    assert "landscape_tables" in {i["code"] for i in report["review_items"]}
    final = docx.Document(path)
    assert final.sections[-1].page_width > final.sections[-1].page_height
    assert final.tables[1].cell(1, 2).text == "Nội dung quan trọng 25%"
    with zipfile.ZipFile(path) as z:
        assert z.read("customXml/unrelated.bin") == b"\x00opaque-part\xff"
    # Existing page fields are replaced, not accumulated on repeat formatting.
    format_minutes_document(path, "nd30_2020", metadata())
    final = docx.Document(path)
    assert len(final.sections[0].header._element.xpath('.//w:fldSimple[@w:instr="PAGE"]')) == 1


def test_party_confirmation_block_uses_only_supplied_information(tmp_path: Path) -> None:
    path = tmp_path / "confirmation.docx"
    shutil.copy2(FIXTURES / "bien_ban_hop_chi_bo.docx", path)
    dm = metadata().model_copy(
        update={
            "party_signature": "confirmation",
            "confirmer_position": "T/L BAN THƯỜNG VỤ\nCHÁNH VĂN PHÒNG",
            "confirmer_name": "Lê Văn C",
        }
    )
    format_minutes_document(path, "hd05_2026", dm)
    cell = docx.Document(path).tables[-1].cell(0, 1)
    assert "Xác nhận chữ ký của đồng chí Nguyễn Văn A" in cell.text
    assert "T/L BAN THƯỜNG VỤ" in cell.text
    assert "Lê Văn C" in cell.text


def test_mixed_front_matter_and_footer_text_are_kept_for_review(tmp_path: Path) -> None:
    path = tmp_path / "mixed.docx"
    d = docx.Document()
    d.add_paragraph("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\nGhi chú bắt buộc từ mẫu")
    d.add_paragraph("BIÊN BẢN")
    d.add_paragraph("Nội dung cần giữ nguyên.")
    footer = d.sections[0].footer.paragraphs[0]
    footer.text = "Thông tin liên hệ nội bộ "
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    footer._p.append(field)
    d.save(path)
    report = format_minutes_document(path, "nd30_2020", metadata())
    final = docx.Document(path)
    assert "Ghi chú bắt buộc từ mẫu" in "\n".join(p.text for p in final.paragraphs)
    assert "Thông tin liên hệ nội bộ" in final.sections[0].footer.paragraphs[0].text
    assert not final.sections[0].footer._element.xpath('.//w:fldSimple[@w:instr="PAGE"]')
    assert {"mixed_front_matter", "retained_header_footer"} <= {
        i["code"] for i in report["review_items"]
    }


def test_incomplete_number_and_explicit_recipient_override(tmp_path: Path) -> None:
    path = tmp_path / "recipients.docx"
    d = docx.Document()
    d.add_paragraph("BIÊN BẢN")
    d.add_paragraph("Nơi nhận:")
    d.add_paragraph("- Nơi nhận cũ;")
    d.add_paragraph("Nội dung tiếp theo được giữ nguyên.")
    d.save(path)
    dm = metadata().model_copy(update={"organization_abbreviation": ""})
    report = format_minutes_document(path, "nd30_2020", dm)
    assert "document_number_missing" in {i["code"] for i in report["review_items"]}
    text = "\n".join(p.text for p in docx.Document(path).paragraphs)
    assert "Nơi nhận cũ" not in text
    assert "Các thành viên" in text
    assert "Nội dung tiếp theo được giữ nguyên." in text


def test_format_and_fact_edits_preserve_configuration_hash_and_zip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import meeting_pipeline.minutes.service as module

    monkeypatch.setattr(module, "render_document_pages", lambda *a: [])
    monkeypatch.setattr(module, "render_document_to_image", lambda *a: None)
    run = tmp_path / "run"
    run.mkdir()
    (run / "timeline.json").write_text('{"segments": []}')
    svc = MinutesService()
    svc.process_template_for_run(
        FIXTURES / "bien_ban_hop_chi_bo.docx",
        run,
        options=MinutesOptions(format_standard="hd05_2026", document_metadata=metadata()),
    )
    facts = json.loads((run / "minutes/facts.json").read_text())
    saved_facts = json.loads((run / "minutes/facts.json").read_text())
    monkeypatch.setattr(module, "run_text_models", lambda *a, **k: pytest.fail("Must not run LLM"))
    svc.reformat_existing(
        run, MinutesOptions(format_standard="nd30_2020", document_metadata=metadata())
    )
    assert json.loads((run / "minutes/facts.json").read_text()) == saved_facts
    svc.update_facts_and_re_render(run, facts)
    configuration = json.loads((run / "minutes/configuration.json").read_text())
    assert configuration["format_standard"] == "nd30_2020"
    assert configuration["document_metadata"]["issue_date"] == "2026-10-15"
    manifest = json.loads((run / "minutes/manifest.json").read_text())
    completed = run / "exports/completed.docx"
    assert manifest["completed_docx_sha256"] == compute_file_sha256(completed)
    with zipfile.ZipFile(run / "exports/completed_minutes.zip") as z:
        assert "formatting_report.json" in z.namelist()
        assert z.read("completed.docx") == completed.read_bytes()
    prior = completed.read_bytes()
    with pytest.raises(ValueError):
        svc.reformat_existing(run, MinutesOptions(two_sided=True))
    assert completed.read_bytes() == prior
    assert json.loads((run / "minutes/configuration.json").read_text()) == configuration
