"""Normalize Word/PDF/scan inputs into editable, reviewable Word templates."""

import json
import re
import shutil
import subprocess

from meeting_backend.core.errors import AppError
from meeting_backend.core.settings import ROOT
from meeting_backend.infrastructure.mongodb.client import new_id, now


def paragraphs(document):
    from docx.oxml.ns import qn
    from docx.text.paragraph import Paragraph

    return [Paragraph(element, document._body) for element in document.element.body.iter(qn("w:p"))]


def reconstruct(source, destination, cache_dir, stage):
    from docx import Document
    from docx.shared import Mm, Pt
    from PIL import Image
    from pypdf import PdfReader

    from meeting_backend.processing.documents.ocr import extract_image

    document = Document()
    section = document.sections[0]
    section.page_width, section.page_height = Mm(210), Mm(297)
    document.styles["Normal"].font.name = "Times New Roman"
    document.styles["Normal"].font.size = Pt(14)
    report = {
        "engine": "pdf_text",
        "needs_review": True,
        "pages": [],
        "warnings": [
            "Tài liệu được tái dựng. Cần đối chiếu đề mục, bảng và trường với bản gốc "
            "trước khi sử dụng."
        ],
    }
    if source.suffix.lower() == ".pdf":
        reader = PdfReader(source)
        if reader.is_encrypted:
            raise AppError(
                "PDF_ENCRYPTED", "PDF có mật khẩu. Hãy mở khóa bản sao trước khi tải.", 422
            )
        if len(reader.pages) > 50:
            raise AppError("PAGE_LIMIT", "Prototype hỗ trợ tối đa 50 trang mỗi mẫu PDF.", 422)
        pages = list(reader.pages)
    else:
        pages = [None]
    for index, page in enumerate(pages):
        stage(f"Đọc/OCR trang {index + 1}/{len(pages)}")
        text = page.extract_text(extraction_mode="layout") if page else ""
        if page and len((text or "").strip()) >= 40:
            elements = [
                {"type": "paragraph", "text": line.strip()}
                for line in text.splitlines()
                if line.strip()
            ]
            summary = {"engine": "pdf_text", "characters": len(text), "table_count": 0}
        else:
            report["engine"] = "ocr_tesseract"
            if page:
                binary = shutil.which("pdftoppm")
                if not binary:
                    raise AppError(
                        "PDF_RENDERER_MISSING", "Cần Poppler/pdftoppm để đọc PDF scan.", 503
                    )
                prefix = destination.parent / f"source-page-{index + 1:04d}"
                result = subprocess.run(
                    [
                        binary,
                        "-f",
                        str(index + 1),
                        "-l",
                        str(index + 1),
                        "-singlefile",
                        "-scale-to",
                        "2600",
                        "-png",
                        str(source),
                        str(prefix),
                    ],
                    capture_output=True,
                    timeout=90,
                )
                image_path = prefix.with_suffix(".png")
                if result.returncode or not image_path.is_file():
                    raise AppError("PDF_RENDER_FAILED", "Không render được trang PDF.", 422)
                image = Image.open(image_path)
            else:
                image = Image.open(source)
            elements, summary = extract_image(
                image, cache_dir, destination.parent / f"ocr-page-{index + 1:04d}.json"
            )
            image.close()
            summary["engine"] = "ocr_tesseract"
        if index:
            document.add_page_break()
        for element in elements:
            if element["type"] == "table":
                rows = element["rows"]
                table = document.add_table(rows=len(rows), cols=len(rows[0]))
                table.style = "Table Grid"
                for row, cells in zip(table.rows, rows, strict=False):
                    for cell, text in zip(row.cells, cells, strict=False):
                        cell.text = text
            else:
                text = element["text"]
                paragraph = document.add_paragraph(text)
                if len(text) < 150 and (text.isupper() or re.match(r"^(?:[IVX]+|\d+)\.[ ]", text)):
                    paragraph.style = "Heading 2"
        report["pages"].append({"page": index + 1, **summary})
    if not any(p.text.strip() for p in paragraphs(document)):
        raise AppError("NO_TEXT_DETECTED", "Không đọc được chữ. Hãy dùng bản scan rõ hơn.", 422)
    document.save(destination)
    return report


def run_template(context):
    from docx import Document

    from meeting_pipeline.minutes.converter import normalize_template
    from meeting_pipeline.minutes.doc_parser import parse_template_document
    from meeting_pipeline.minutes.schema_mapper import M0RuleSchemaMapper, SchemaValidator
    from meeting_pipeline.minutes.schemas import TemplateField
    from meeting_pipeline.minutes.visual_qa import render_document_pages

    context.stage("Đọc mẫu và chuẩn hóa tài liệu")
    template = context.resource()
    normalized = context.staging / "normalized.docx"
    original = context.mongo.db.artifacts.find_one({"_id": template["input_artifact_id"]})
    source = context.store.resolve(original)
    reviewing = context.job["kind"] == "review_template"
    if reviewing:
        prior = context.mongo.db.template_versions.find_one({"_id": template["active_version_id"]})
        old = context.mongo.db.artifacts.find_one({"_id": prior["normalized"]["id"]})
        shutil.copy2(context.store.resolve(old), normalized)
        report = prior["report"]
        document = Document(normalized)
        items = paragraphs(document)
        for patch in context.job["payload"].get("paragraphs", []):
            index = patch.get("index")
            text = patch.get("text")
            if (
                not isinstance(index, int)
                or not 0 <= index < len(items)
                or not isinstance(text, str)
                or len(text) > 12000
            ):
                raise AppError("INVALID_PARAGRAPH", "Đoạn sửa trong mẫu không hợp lệ.", 422)
            items[index].text = text
        document.save(normalized)
    elif source.suffix.lower() in {".doc", ".docx"}:
        conversion = normalize_template(source, context.staging)
        normalized = conversion.normalized_docx_path
        report = {
            "engine": conversion.conversion_engine,
            "needs_review": False,
            "warnings": list(conversion.conversion_warnings),
            "pages": [],
        }
    else:
        report = reconstruct(source, normalized, ROOT / "data/ocr_cache", context.stage)
    context.stage("Phân tích đề mục, vị trí điền và kiểm tra mẫu")
    graph = parse_template_document(
        normalized, original_sha256=original["sha256"], template_id=template["_id"]
    )
    schema = M0RuleSchemaMapper().propose_schema(graph)
    if reviewing and context.job["payload"].get("fields"):
        supplied = [TemplateField.model_validate(f) for f in context.job["payload"]["fields"]]
        validated, unmapped, issues = SchemaValidator.validate(graph, supplied)
        if issues or len({field.field_id for field in validated}) != len(validated):
            raise AppError(
                "INVALID_TEMPLATE_FIELDS",
                "Các trường hoặc vị trí điền không hợp lệ: " + "; ".join(issues),
                422,
            )
        schema.fields = validated
        schema.unmapped_anchors = unmapped
        schema.proposed_by = "user_manual"
        report = {**report, "schema_issues": issues}
    if reviewing and context.job["payload"].get("paragraphs"):
        report = {**report, "needs_review": True}
        if context.job["payload"].get("approved"):
            raise AppError(
                "REVIEW_AFTER_TEXT_EDIT",
                "Hãy lưu chữ đã sửa, sau đó duyệt lại trường ở phiên bản mới.",
                422,
            )
    if reviewing and context.job["payload"].get("approved"):
        report = {
            **report,
            "needs_review": False,
            "reviewed_by": template["owner_id"],
            "reviewed_at": now(),
        }
        schema.proposed_by = "user_manual"
        for field in schema.fields:
            field.mapper_status = "approved"
    (context.staging / "schema.json").write_text(
        json.dumps(schema.model_dump(), ensure_ascii=False, indent=2)
    )
    (context.staging / "doc_graph.json").write_text(
        json.dumps(graph.model_dump(), ensure_ascii=False, indent=2)
    )
    previews = []
    try:
        context.stage("Tạo bản xem trước các trang mẫu")
        pages = render_document_pages(normalized, context.staging / "preview")
    except Exception as exc:
        pages = []
        report = {**report, "preview_error": str(exc)}
    final = context.root / "templates" / template["_id"] / context.job["_id"]
    final.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(context.staging), final)
    normalized = final / normalized.name
    for page in pages:
        previews.append(
            context.artifact(final / "preview" / page.name, visibility=template["visibility"])
        )
    text_rows = [
        {"index": i, "text": p.text} for i, p in enumerate(paragraphs(Document(normalized)))
    ]
    if len(text_rows) > 2000:
        raise AppError("PARAGRAPH_LIMIT", "Mẫu quá dài cho chế độ rà soát prototype.", 422)
    version = {
        "_id": new_id(),
        "owner_id": template["owner_id"],
        "template_id": template["_id"],
        "created_at": now(),
        "parent_id": template.get("active_version_id"),
        "report": report,
        "schema": schema.model_dump(),
        "paragraphs": text_rows,
        "previews": previews,
        "normalized": context.artifact(
            normalized, visibility=template["visibility"], name=template["name"] + ".docx"
        ),
        "original": context.store.view(original),
        "ocr_reports": [
            context.artifact(p, visibility=template["visibility"])
            for p in final.glob("ocr-page-*.json")
        ],
    }
    context.mongo.db.template_versions.insert_one(version)
    context.publish(
        {
            "active_version_id": version["_id"],
            "needs_review": report.get("needs_review", False),
            "state": "ready",
            "field_count": len(schema.fields),
        },
        result={"template_version_id": version["_id"]},
    )
