"""Visual QA rendering utility for Word documents before and after form filling.

Generates high-resolution PNG previews using macOS QuickLook (qlmanage) to
allow visual layout inspection without external heavy dependencies.
Specification: Section 5 (F1, F4) of docs/PLAN_BIEU_MAU_BIEN_BAN_V1.md.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class VisualRenderError(Exception):
    """Raised when rendering a document to an image preview fails."""


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
