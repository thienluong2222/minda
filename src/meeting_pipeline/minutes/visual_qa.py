"""Full-page Word previews via LibreOffice/Poppler and optional QuickLook thumbnails."""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from meeting_pipeline.minutes.document_tools import find_document_tool

logger = logging.getLogger(__name__)


class VisualRenderError(Exception):
    """Raised when rendering a document to an image preview fails."""


def render_document_pages(doc_path: Path, output_dir: Path) -> list[Path]:
    """Render every page with LibreOffice/Poppler, using an isolated LO profile.

    Optional local tools; callers report absence instead of claiming visual QA.
    PDF and PNG files are previews, not the editable export.
    """
    soffice = find_document_tool("soffice")
    pdftoppm = find_document_tool("pdftoppm")
    if not soffice or not pdftoppm:
        raise VisualRenderError(
            "Chưa tìm thấy LibreOffice hoặc Poppler để xem trước DOCX. "
            "Cần cài cả hai công cụ trên máy chạy worker."
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="minutes-lo-") as temp:
        pdf_dir = Path(temp) / "pdf"
        pdf_dir.mkdir()
        profile = (Path(temp) / "profile").as_uri()
        converted = subprocess.run(
            [
                soffice,
                "--headless",
                f"-env:UserInstallation={profile}",
                "--convert-to",
                "pdf",
                "--outdir",
                str(pdf_dir),
                str(doc_path.resolve()),
            ],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        pdf = pdf_dir / f"{doc_path.stem}.pdf"
        if converted.returncode or not pdf.is_file():
            raise VisualRenderError("Không thể tạo bản xem trước PDF bằng LibreOffice.")
        # Remove stale pages only after the new conversion succeeds.
        for old in output_dir.glob("page-*.png"):
            old.unlink()
        rendered = subprocess.run(
            [pdftoppm, "-scale-to", "1400", "-png", str(pdf), str(output_dir / "page")],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        pages = sorted(output_dir.glob("page-*.png"), key=lambda p: int(p.stem.split("-")[-1]))
        if rendered.returncode or not pages:
            raise VisualRenderError("Không thể tạo ảnh xem trước từng trang bằng Poppler.")
        return pages


def render_document_to_image(
    doc_path: Path,
    output_dir: Path,
    image_name: str | None = None,
    size: int = 1200,
) -> Path:
    """Render a Word document (.doc or .docx) to a PNG preview image."""
    if not doc_path.is_file():
        raise FileNotFoundError(f"Document to render not found: {doc_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    qlmanage_path = shutil.which("qlmanage")

    if not qlmanage_path:
        raise VisualRenderError("qlmanage utility is not available on this operating system.")

    try:
        # Run qlmanage thumbnail generator
        cmd = [
            qlmanage_path,
            "-t",
            "-s",
            str(size),
            "-o",
            str(output_dir),
            str(doc_path),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)

        # qlmanage saves as <original_filename>.png in output_dir
        expected_output = output_dir / f"{doc_path.name}.png"
        if not expected_output.is_file():
            # Sometimes qlmanage names it without .png or with .doc.png
            candidates = list(output_dir.glob(f"{doc_path.stem}*"))
            png_candidates = [c for c in candidates if c.suffix.lower() == ".png"]
            if png_candidates:
                expected_output = png_candidates[0]
            else:
                raise VisualRenderError(
                    f"qlmanage returned {res.returncode} but output PNG was not created"
                )

        target_name = image_name or f"{doc_path.stem}_preview.png"
        if not target_name.endswith(".png"):
            target_name += ".png"

        final_path = output_dir / target_name
        if expected_output != final_path:
            expected_output.replace(final_path)

        logger.info("Rendered visual preview for %s -> %s", doc_path.name, final_path)
        return final_path

    except Exception as exc:
        raise VisualRenderError(
            f"Failed to render document preview for {doc_path.name}: {exc}"
        ) from exc
