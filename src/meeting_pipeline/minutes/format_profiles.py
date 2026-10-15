"""Versioned rules transcribed from official document presentation standards.

ND30: Annex I and Annex III, form 1.9 of 30/2020/ND-CP.
HD05: Part II, sections I/IV and Annex II of 05-HD/VPTW, 27 May 2026.
These rules are deterministic and never inferred by a language model.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FormatStandard = Literal["nd30_2020", "hd05_2026"]


class DocumentMetadata(BaseModel):
    """Explicit user input for information absent from the uploaded template."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    parent_organization: str = Field(default="", max_length=300)
    organization: str = Field(default="", max_length=300)
    organization_abbreviation: str = Field(default="", max_length=40)
    document_number: str = Field(default="", max_length=100)
    issue_place: str = Field(default="", max_length=200)
    issue_date: date | None = None
    chairperson: str = Field(default="", max_length=200)
    secretary: str = Field(default="", max_length=200)
    recipients: str = Field(default="", max_length=2000)
    party_signature: Literal["review", "direct", "confirmation"] = "review"
    confirmer_position: str = Field(default="", max_length=300)
    confirmer_name: str = Field(default="", max_length=200)


@dataclass(frozen=True)
class FormatProfile:
    standard: FormatStandard
    label: str
    source: str
    body_pt: int
    title_pt: int
    subtitle_pt: int
    line_spacing: float
    exact_spacing: bool
    organization_pt: int
    number_pt: int


PROFILES: dict[str, FormatProfile] = {
    "nd30_2020": FormatProfile(
        "nd30_2020",
        "Nghị định 30/2020/NĐ-CP",
        "https://datafiles.chinhphu.vn/cpp/files/vbpq/2020/03/30.signed.pdf",
        14,
        14,
        14,
        1.15,
        False,
        13,
        13,
    ),
    "hd05_2026": FormatProfile(
        "hd05_2026",
        "Hướng dẫn 05-HD/VPTW ngày 27/5/2026",
        "https://tulieuvankien.dangcongsan.vn/upload/2006988/20260529/HD_05_VPTW_e1550.pdf",
        14,
        16,
        14,
        20,
        True,
        14,
        14,
    ),
}
