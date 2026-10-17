"""Locate document tools in both shell and desktop-launched environments."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Literal

DocumentTool = Literal["soffice", "pdftoppm"]

TOOL_LOCATIONS: dict[DocumentTool, tuple[str, ...]] = {
    "soffice": (
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        "/opt/homebrew/bin/soffice",
        "/usr/local/bin/soffice",
        "/usr/bin/soffice",
    ),
    "pdftoppm": (
        "/opt/homebrew/bin/pdftoppm",
        "/usr/local/bin/pdftoppm",
        "/usr/bin/pdftoppm",
    ),
}


def find_document_tool(name: DocumentTool) -> str | None:
    """Prefer PATH, then standard installs; never depend on a Codex-only runtime."""
    aliases = ("soffice", "libreoffice") if name == "soffice" else (name,)
    for alias in aliases:
        executable = shutil.which(alias)
        if executable:
            return executable
    for location in TOOL_LOCATIONS[name]:
        path = Path(location)
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def preview_tools() -> dict[str, str | None]:
    return {
        "libreoffice": find_document_tool("soffice"),
        "pdftoppm": find_document_tool("pdftoppm"),
    }
