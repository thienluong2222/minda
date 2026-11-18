"""Word template conversion and format normalization service.

Converts .doc binary to .docx on a copy using macOS textutil or LibreOffice,
preserving original files and validating integrity with SHA-256 hashes.
Specification: Section 5 (F1) of docs/PLAN_BIEU_MAU_BIEN_BAN_V1.md.
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
import subprocess
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import docx

from meeting_pipeline.minutes.document_tools import find_document_tool

logger = logging.getLogger(__name__)

DOC_OLE_HEADER = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
DOCX_ZIP_HEADER = b"PK\x03\x04"


class UnsupportedFormatError(Exception):
    """Raised when an uploaded template is neither a supported .doc nor .docx."""


class DocumentConversionError(Exception):
    """Raised when converting .doc binary to .docx fails."""


@dataclass
class ConvertedTemplate:
    """Result of normalizing a Word template to a working DOCX copy."""

    original_path: Path
    normalized_docx_path: Path
    original_sha256: str
    normalized_docx_sha256: str
    original_format: str  # "doc" or "docx"
    convert_duration_sec: float
    conversion_engine: str = "copy"
    conversion_warnings: tuple[str, ...] = ()


def compute_file_sha256(path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def detect_word_format(path: Path) -> str:
    """Inspect file header bytes and extension to detect doc or docx."""
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")

    with path.open("rb") as f:
        header = f.read(8)

    ext = path.suffix.lower()

    if header.startswith(DOCX_ZIP_HEADER) or ext == ".docx":
        # Check if really valid zip/docx
        try:
            docx.Document(str(path))
            return "docx"
        except Exception as exc:
            if not header.startswith(DOC_OLE_HEADER):
                raise UnsupportedFormatError(
                    f"Tệp tin {path.name} có đuôi .docx nhưng lỗi OOXML: {exc}"
                ) from exc

    if header.startswith(DOC_OLE_HEADER) or ext == ".doc":
        return "doc"

    raise UnsupportedFormatError(
        f"Định dạng tệp tin '{path.name}' không được hỗ trợ. "
        "Pipeline v1.0 chỉ hỗ trợ định dạng Microsoft Word (.doc và .docx)."
    )


def convert_doc_to_docx(src_doc: Path, dst_docx: Path) -> str:
    """Convert .doc binary to .docx on a copy using macOS textutil or LibreOffice."""
    dst_docx.parent.mkdir(parents=True, exist_ok=True)

    # Prefer a Word-aware converter for tables, headers, fields and page setup.
    soffice_path = find_document_tool("soffice")
    if soffice_path:
        try:
            with tempfile.TemporaryDirectory(prefix="minutes-convert-") as temp:
                profile = (Path(temp) / "profile").as_uri()
                res = subprocess.run(
                    [
                        soffice_path,
                        "--headless",
                        f"-env:UserInstallation={profile}",
                        "--convert-to",
                        "docx",
                        "--outdir",
                        temp,
                        str(src_doc.resolve()),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=60,
                )
                generated = Path(temp) / f"{src_doc.stem}.docx"
                if res.returncode == 0 and generated.is_file():
                    docx.Document(str(generated))
                    shutil.copy2(generated, dst_docx)
                    return "libreoffice"
        except Exception as exc:
            logger.warning("LibreOffice conversion attempt failed: %s", exc)

    # macOS fallback; its layout limitations are surfaced in the export report.
    try:
        cmd = ["textutil", "-convert", "docx", "-output", str(dst_docx), str(src_doc)]
        res = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=60)
        if res.returncode == 0 and dst_docx.is_file() and dst_docx.stat().st_size > 0:
            # Verify valid docx
            docx.Document(str(dst_docx))
            logger.info("Successfully converted .doc to .docx using textutil: %s", dst_docx)
            return "textutil"
    except Exception as exc:
        logger.warning("textutil conversion attempt failed: %s", exc)

    raise DocumentConversionError(
        f"Không thể chuyển đổi tệp .doc binary '{src_doc.name}' sang .docx. "
        "Yêu cầu tiện ích textutil (macOS) hoặc LibreOffice (soffice)."
    )


def normalize_template(
    template_path: Path,
    output_dir: Path,
    filename_prefix: str = "normalized",
) -> ConvertedTemplate:
    """Normalize uploaded Word template to a verified DOCX working copy."""
    t0 = time.perf_counter()
    fmt = detect_word_format(template_path)
    orig_sha = compute_file_sha256(template_path)

    output_dir.mkdir(parents=True, exist_ok=True)
    dst_docx = output_dir / f"{filename_prefix}.docx"
    engine = "copy"
    warnings: list[str] = []

    if fmt == "docx":
        # Copy original docx to working copy
        shutil.copy2(template_path, dst_docx)
        # Verify
        try:
            docx.Document(str(dst_docx))
        except Exception as exc:
            raise UnsupportedFormatError(
                f"Tệp .docx '{template_path.name}' bị lỗi cấu trúc: {exc}"
            ) from exc
    elif fmt == "doc":
        engine = convert_doc_to_docx(template_path, dst_docx)
        if engine == "textutil":
            warnings.append(
                "DOC được chuyển bằng textutil; cần đối chiếu bảng, đầu/cuối trang "
                "và đối tượng nhúng với bản gốc."
            )
        if shutil.which("textutil"):
            try:
                source = subprocess.run(
                    ["textutil", "-convert", "txt", "-stdout", str(template_path)],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30,
                )
                destination = docx.Document(str(dst_docx))
                text = " ".join(destination.element.body.xpath(".//w:t/text()"))
                missing = Counter(re.findall(r"\w+", source.stdout.casefold())) - Counter(
                    re.findall(r"\w+", text.casefold())
                )
                if source.returncode or not source.stdout.strip():
                    warnings.append("Chưa đối chiếu được văn bản nguồn DOC; cần kiểm tra bản gốc.")
                elif missing:
                    warnings.append(
                        f"Có {sum(missing.values())} từ nguồn chưa khớp sau chuyển DOC; "
                        "cần đối chiếu bản gốc và bản xem trước."
                    )
            except (OSError, subprocess.TimeoutExpired):
                warnings.append("Chưa đối chiếu được văn bản nguồn DOC; cần kiểm tra bản gốc.")
        else:
            warnings.append("Chưa có bộ đọc DOC độc lập để đối chiếu nội dung sau chuyển đổi.")
    else:
        raise UnsupportedFormatError(f"Định dạng '{fmt}' không được hỗ trợ.")

    norm_sha = compute_file_sha256(dst_docx)
    dur = time.perf_counter() - t0

    return ConvertedTemplate(
        original_path=template_path,
        normalized_docx_path=dst_docx,
        original_sha256=orig_sha,
        normalized_docx_sha256=norm_sha,
        original_format=fmt,
        convert_duration_sec=dur,
        conversion_engine=engine,
        conversion_warnings=tuple(warnings),
    )
