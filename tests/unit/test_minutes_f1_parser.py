"""Unit tests for Phase F1: OOXML parsing, anchor extraction, and visual QA."""

from __future__ import annotations

from pathlib import Path

import pytest

from meeting_pipeline.minutes.converter import (
    UnsupportedFormatError,
    detect_word_format,
    normalize_template,
)
from meeting_pipeline.minutes.doc_parser import parse_template_document
from meeting_pipeline.minutes.visual_qa import render_document_to_image

FIXTURES_DIR = Path("tests/fixtures/templates")


def test_converter_doc_and_docx(tmp_path: Path) -> None:
    """Test format detection and normalization of both .doc binary and .docx."""
    doc_path = FIXTURES_DIR / "mau_bien_ban_hop_chung.doc"
    docx_path = FIXTURES_DIR / "bien_ban_hop_chi_bo.docx"

    assert detect_word_format(doc_path) == "doc"
    assert detect_word_format(docx_path) == "docx"

    # Normalize .doc binary -> .docx working copy
    out_dir_1 = tmp_path / "out_doc"
    converted_doc = normalize_template(doc_path, out_dir_1)
    assert converted_doc.original_format == "doc"
    assert converted_doc.normalized_docx_path.is_file()
    assert converted_doc.normalized_docx_path.suffix == ".docx"
    assert len(converted_doc.original_sha256) == 64
    assert len(converted_doc.normalized_docx_sha256) == 64

    # Normalize native .docx -> working copy
    out_dir_2 = tmp_path / "out_docx"
    converted_docx = normalize_template(docx_path, out_dir_2)
    assert converted_docx.original_format == "docx"
    assert converted_docx.normalized_docx_path.is_file()
    assert converted_docx.original_sha256 == converted_docx.normalized_docx_sha256


def test_converter_unsupported_format(tmp_path: Path) -> None:
    """Reject non-Word files with clear error explanation."""
    fake_txt = tmp_path / "invalid.txt"
    fake_txt.write_text("Hello World", encoding="utf-8")

    with pytest.raises(UnsupportedFormatError):
        normalize_template(fake_txt, tmp_path / "out")


def test_parse_mau_bien_ban_hop_chung(tmp_path: Path) -> None:
    """Verify candidate anchors extracted from mau_bien_ban_hop_chung."""
    doc_path = FIXTURES_DIR / "mau_bien_ban_hop_chung.doc"
    converted = normalize_template(doc_path, tmp_path / "norm")

    graph = parse_template_document(
        converted.normalized_docx_path, original_sha256=converted.original_sha256
    )

    assert graph.template_id == converted.normalized_docx_path.stem
    assert len(graph.blocks) > 10
    anchors = graph.all_anchors
    assert len(anchors) >= 20

    # Verify no anchor has invented / invalid paths
    anchor_ids = [a.anchor_id for a in anchors]
    assert len(anchor_ids) == len(set(anchor_ids)), "Anchor IDs must be unique"

    # Verify specific key placeholders are detected
    labels = [a.nearby_label.lower() for a in anchors]
    assert any("chủ trì" in lbl for lbl in labels)
    assert any("chức vụ" in lbl for lbl in labels)
    assert any("thư ký" in lbl for lbl in labels)
    assert any("tán thành" in lbl for lbl in labels)


def test_parse_bien_ban_hop_chi_bo(tmp_path: Path) -> None:
    """Verify candidate anchors extracted from bien_ban_hop_chi_bo.docx."""
    docx_path = FIXTURES_DIR / "bien_ban_hop_chi_bo.docx"
    converted = normalize_template(docx_path, tmp_path / "norm")

    graph = parse_template_document(
        converted.normalized_docx_path, original_sha256=converted.original_sha256
    )

    anchors = graph.all_anchors
    assert len(anchors) >= 18

    # Verify table anchors and paragraphs in cell detected
    tbl_anchors = [a for a in anchors if "table" in a.element_path]
    assert len(tbl_anchors) >= 2  # Table 0 has Đảng ủy and Chi bộ anchors
    tbl_labels = [a.nearby_label.upper() for a in tbl_anchors]
    assert any("ĐẢNG ỦY" in lbl for lbl in tbl_labels)
    assert any("CHI BỘ" in lbl for lbl in tbl_labels)


def test_visual_qa_rendering(tmp_path: Path) -> None:
    """Render documents to PNG images for visual layout inspection."""
    doc_path = FIXTURES_DIR / "mau_bien_ban_hop_chung.doc"
    docx_path = FIXTURES_DIR / "bien_ban_hop_chi_bo.docx"

    out_img_1 = render_document_to_image(doc_path, tmp_path / "img1", "mau_chung_before.png")
    assert out_img_1.is_file()
    assert out_img_1.stat().st_size > 5000

    out_img_2 = render_document_to_image(docx_path, tmp_path / "img2", "chi_bo_before.png")
    assert out_img_2.is_file()
    assert out_img_2.stat().st_size > 5000
