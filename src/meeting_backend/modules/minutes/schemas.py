from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from meeting_backend.modules.meetings.schemas import Revision


class MinutesOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["detailed", "general"] = "detailed"
    use_model: bool = True
    correct_transcript: bool = True
    use_fcm: bool = True
    clusters: int | None = Field(None, ge=1, le=12)
    content_field_id: str | None = None
    format_standard: Literal["nd30_2020", "hd05_2026"] = "nd30_2020"
    two_sided: bool = False
    document_metadata: dict = Field(default_factory=dict)


class GenerateMinutes(Revision):
    template_id: str
    options: MinutesOptions = Field(default_factory=MinutesOptions)


class FactPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field_id: str
    value: str | list[str] | None = None
    status: Literal["supported", "unknown", "conflicting", "needs_review"] | None = None
    reason: str | None = Field(None, max_length=2000)


class EditFacts(Revision):
    patches: list[FactPatch] = Field(max_length=500)


class Reformat(Revision):
    options: MinutesOptions


class RestoreMinutes(Revision):
    version_id: str
