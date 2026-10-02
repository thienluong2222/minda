"""Unit tests for Phase F4: Word Copy Rendering, Traceability Manifest & Minutes Service.

Specification: Section 3, 5 (F4), and 6 of docs/PLAN_BIEU_MAU_BIEN_BAN_V1.md.
Gate F4: hai mẫu Word xuất file mở được; ảnh render trước/sau đã được người làm kiểm;
không tràn/chồng trên ca thử; click từ giá trị đến clip hoặc metadata được phép;
sửa schema/value không gọi ASR; run cũ vẫn mở được.
"""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import docx

from meeting_pipeline.minutes.converter import normalize_template
from meeting_pipeline.minutes.doc_parser import parse_template_document
from meeting_pipeline.minutes.renderer import render_completed_document
from meeting_pipeline.minutes.schema_mapper import M0RuleSchemaMapper
from meeting_pipeline.minutes.schemas import FactStatus, MeetingFact
from meeting_pipeline.minutes.service import MinutesService

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"
TEMPLATES_DIR = FIXTURES_DIR / "templates"
AUDIO_RUN_DIR = (
    REPO_ROOT / "data" / "meetings" / "1" / "runs" / "a6e814e4-ea36-4cc9-8992-ba60b9341ea5"
)


def test_render_completed_docx_chi_bo(tmp_path: Path) -> None:
    """Test rendering facts into bien_ban_hop_chi_bo.docx copy and verifying it opens."""
    template_src = TEMPLATES_DIR / "bien_ban_hop_chi_bo.docx"
    assert template_src.is_file()

    # 1. Normalize
    converted = normalize_template(template_src, tmp_path, "chi_bo_norm")
    assert converted.normalized_docx_path.is_file()

    # 2. Parse DocGraph
    doc_graph = parse_template_document(
        converted.normalized_docx_path,
        original_sha256=converted.original_sha256,
        template_id="bien_ban_hop_chi_bo",
    )

    # 3. Propose schema
    mapper = M0RuleSchemaMapper()
    schema = mapper.propose_schema(doc_graph)

    # 4. Create synthetic facts for test matching canonical field IDs
    facts = [
        MeetingFact(
            field_id="start_time",
            value="14 giờ 30 phút, ngày 15 tháng 10 năm 2026",
            status=FactStatus.SUPPORTED,
            source_turn_indices=[0],
            confidence=0.95,
        ),
        MeetingFact(
            field_id="location",
            value="Phòng họp Chi bộ 1, Tầng 3",
            status=FactStatus.SUPPORTED,
            source_turn_indices=[1],
            confidence=0.9,
        ),
        MeetingFact(
            field_id="chairperson_name",
            value="Đồng chí Nguyễn Văn A, Bí thư Chi bộ",
            status=FactStatus.SUPPORTED,
            source_turn_indices=[2],
            confidence=0.92,
        ),
        MeetingFact(
            field_id="secretary_name",
            value="Đồng chí Trần Thị B, Đảng viên",
            status=FactStatus.SUPPORTED,
            confidence=0.88,
        ),
        MeetingFact(
            field_id="party_dues",
            value=None,
            status=FactStatus.UNKNOWN,
            notes="Âm thanh không đề cập đến việc đóng đảng phí.",
        ),
    ]

    # 5. Render completed document
    output_docx = tmp_path / "completed_chi_bo.docx"
    rendered_path, docx_sha = render_completed_document(
        normalized_docx_path=converted.normalized_docx_path,
        output_docx_path=output_docx,
        doc_graph=doc_graph,
        schema=schema,
        facts=facts,
    )

    assert rendered_path.is_file()
    assert len(docx_sha) == 64

    # Gate F4 check: File must be openable by docx
    doc = docx.Document(output_docx)
    all_text = "\n".join(p.text for p in doc.paragraphs)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                all_text += "\n" + cell.text

    assert "14 giờ 30 phút, ngày 15 tháng 10 năm 2026" in all_text
    assert "Phòng họp Chi bộ 1, Tầng 3" in all_text


def test_render_completed_doc_binary(tmp_path: Path) -> None:
    """Test converting .doc binary to docx and rendering completed document."""
    template_src = TEMPLATES_DIR / "mau_bien_ban_hop_chung.doc"
    assert template_src.is_file()

    converted = normalize_template(template_src, tmp_path, "chung_norm")
    assert converted.normalized_docx_path.is_file()

    doc_graph = parse_template_document(
        converted.normalized_docx_path,
        original_sha256=converted.original_sha256,
        template_id="mau_bien_ban_hop_chung",
    )

    mapper = M0RuleSchemaMapper()
    schema = mapper.propose_schema(doc_graph)

    facts = [
        MeetingFact(
            field_id="start_time",
            value="08 giờ 30 phút, ngày 20 tháng 11 năm 2026",
            status=FactStatus.SUPPORTED,
        ),
        MeetingFact(
            field_id="location",
            value="Hội trường lớn A",
            status=FactStatus.SUPPORTED,
        ),
        MeetingFact(
            field_id="chairperson_name",
            value="Ông Lê Văn C - Giám đốc",
            status=FactStatus.SUPPORTED,
        ),
        MeetingFact(
            field_id="secretary_name",
            value="Bà Phạm Thị D - Thư ký",
            status=FactStatus.SUPPORTED,
        ),
    ]

    output_docx = tmp_path / "completed_chung.docx"
    rendered_path, docx_sha = render_completed_document(
        normalized_docx_path=converted.normalized_docx_path,
        output_docx_path=output_docx,
        doc_graph=doc_graph,
        schema=schema,
        facts=facts,
    )

    assert rendered_path.is_file()
    doc = docx.Document(output_docx)
    all_text = "\n".join(p.text for p in doc.paragraphs)
    assert "08 giờ 30 phút, ngày 20 tháng 11 năm 2026" in all_text
    assert "Hội trường lớn A" in all_text


def test_minutes_service_end_to_end_orchestration(tmp_path: Path) -> None:
    """Test full MinutesService processing from audio run to completed.docx and manifest."""
    # Copy audio run fixture to isolated test directory
    run_dir = tmp_path / "test_run"
    shutil.copytree(AUDIO_RUN_DIR, run_dir)

    template_file = TEMPLATES_DIR / "mau_bien_ban_hop_chung.doc"
    service = MinutesService()

    result = service.process_template_for_run(
        template_file_path=template_file,
        run_dir=run_dir,
        meeting_metadata={"meeting_name": "Cuộc họp thử nghiệm giao ban"},
        use_model=False,
    )

    assert result["status"] == "success"
    assert result["fields_count"] > 0
    assert Path(result["completed_docx"]).is_file()
    assert Path(result["manifest_json"]).is_file()
    assert Path(result["zip_export"]).is_file()

    # Inspect manifest
    manifest_data = json.loads(Path(result["manifest_json"]).read_text(encoding="utf-8"))
    assert manifest_data["schema_version"] in ("1.0", "2.0")
    assert manifest_data["run_id"] == "test_run"
    assert len(manifest_data["facts"]) > 0
    assert len(manifest_data["fields"]) > 0

    # Verify zip content
    with zipfile.ZipFile(result["zip_export"], "r") as zf:
        namelist = zf.namelist()
        assert "completed.docx" in namelist
        assert "manifest.json" in namelist
        assert "facts.json" in namelist
        assert "schema.json" in namelist


def test_update_facts_without_asr(tmp_path: Path) -> None:
    """Verify that user editing facts re-renders Word document without calling ASR."""
    run_dir = tmp_path / "test_run_edit"
    shutil.copytree(AUDIO_RUN_DIR, run_dir)

    template_file = TEMPLATES_DIR / "bien_ban_hop_chi_bo.docx"
    service = MinutesService()

    service.process_template_for_run(
        template_file_path=template_file,
        run_dir=run_dir,
        use_model=False,
    )

    facts_path = run_dir / "minutes" / "facts.json"
    facts = json.loads(facts_path.read_text(encoding="utf-8"))

    # Modify one fact manually
    target_found = False
    for f in facts:
        if f["field_id"] == "start_time":
            f["value"] = "15 giờ 00 ngày 01 tháng 01 năm 2030 (ĐÃ SỬA TAY)"
            target_found = True
            break
    assert target_found

    # Call update_facts_and_re_render
    updated_docx = service.update_facts_and_re_render(run_dir, facts)
    assert updated_docx.is_file()

    # Verify updated docx contains new text
    doc = docx.Document(updated_docx)
    all_text = "\n".join(p.text for p in doc.paragraphs)
    assert "15 giờ 00 ngày 01 tháng 01 năm 2030 (ĐÃ SỬA TAY)" in all_text

    # Verify manifest reflects user_edited and revision increment
    manifest_data = json.loads((run_dir / "minutes" / "manifest.json").read_text(encoding="utf-8"))
    time_fact_manifest = next(f for f in manifest_data["facts"] if f["field_id"] == "start_time")
    assert time_fact_manifest["user_edited"] is True
    assert time_fact_manifest["transcript_revision"] >= 1
