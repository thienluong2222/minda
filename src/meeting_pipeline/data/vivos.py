"""VIVOS dataset utilities and Vietnamese text normalization.

Specification: Section 6 & 11.2 of docs/PLAN_VIVOS_SYNTHETIC_PIPELINE.md.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path


def normalize_vietnamese_text(text: str) -> str:
    """Normalize Vietnamese text into standard lowercased NFC form.

    Applies:
    1. Unicode NFC normalization.
    2. Lowercasing.
    3. Removal of punctuation marks and control characters while preserving Vietnamese accents.
    4. Collapse consecutive whitespace into a single space and strip boundaries.
    """
    if not text:
        return ""

    # Unicode NFC normalization
    normalized = unicodedata.normalize("NFC", text.strip())

    # Lowercase
    normalized = normalized.lower()

    # Remove standard punctuation, keeping letters, digits, and spaces
    # Vietnamese accented letters are preserved by \\w in re with unicode support
    # Replace punctuation characters with space
    normalized = re.sub(r"[^\w\s]", " ", normalized, flags=re.UNICODE)

    # Collapse multiple whitespaces
    normalized = re.sub(r"\s+", " ", normalized).strip()

    return normalized


def parse_vivos_prompts(prompts_file: Path | str) -> dict[str, str]:
    """Parse VIVOS prompts.txt file into a mapping of utterance_id -> raw_text.

    Format of prompts.txt:
    VIVOSSPK01_001 TÔI MUỐN ĐI HỌC
    """
    path = Path(prompts_file)
    if not path.is_file():
        raise FileNotFoundError(f"Prompts file not found at: {path}")

    prompts: dict[str, str] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(" ", 1)
            if len(parts) == 2:
                utt_id, text = parts
                prompts[utt_id.strip()] = text.strip()
            elif len(parts) == 1:
                prompts[parts[0].strip()] = ""

    return prompts
