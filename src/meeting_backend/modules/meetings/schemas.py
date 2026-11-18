from pydantic import BaseModel, ConfigDict, Field


class MeetingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    date: str = ""
    location: str = Field("", max_length=300)
    notes: str = Field("", max_length=4000)
    participant_ids: list[str] = Field(default_factory=list, max_length=8)
    preferred_template_id: str | None = None
    preferred_format: str = Field("nd30_2020", pattern="^(nd30_2020|hd05_2026)$")
    preferred_mode: str = Field("detailed", pattern="^(detailed|general)$")


class Revision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)


class MeetingUpdate(Revision):
    title: str | None = Field(None, min_length=1, max_length=200)
    date: str | None = None
    location: str | None = Field(None, max_length=300)
    notes: str | None = Field(None, max_length=4000)
    participant_ids: list[str] | None = Field(None, max_length=8)
