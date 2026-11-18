from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from meeting_backend.modules.meetings.schemas import Revision
from meeting_pipeline.minutes.graph_plan import PlannedSectionEdit


class MinutesOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["detailed", "general"] = "detailed"
    use_model: bool = True
    # Accept the saved options object from existing clients; generation policy is server-owned.
    graph_enabled: bool = False
    correct_transcript: bool = True
    use_fcm: bool = True
    clusters: int | None = Field(None, ge=1, le=12)
    content_field_id: str | None = None
    format_standard: Literal["nd30_2020", "hd05_2026", "minimal"] = "nd30_2020"
    two_sided: bool = False
    document_metadata: dict = Field(default_factory=dict)


class GenerateMinutes(Revision):
    template_id: str
    options: MinutesOptions = Field(default_factory=MinutesOptions)
    agenda: list[str] = Field(default_factory=list, max_length=64)
    turn_sessions: dict[str, str] = Field(default_factory=dict, max_length=50000)


class FactPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field_id: str
    value: str | list[str] | None = None
    status: Literal["supported", "unknown", "conflicting", "needs_review"] | None = None
    reason: str | None = Field(None, max_length=2000)


class EditFacts(Revision):
    patches: list[FactPatch] = Field(max_length=500)


class ReviseOutline(Revision):
    version_id: str
    plan_id: str
    sections: list[PlannedSectionEdit] = Field(max_length=512)


class Reformat(Revision):
    options: MinutesOptions


class RestoreMinutes(Revision):
    version_id: str
