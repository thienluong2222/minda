from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Preset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(1, ge=1)
    identity_method: Literal["prototype_cosine", "mfcc_knn"] = "prototype_cosine"
    fusion_method: Literal[
        "F1_BEST_SEGMENT",
        "F3_ROVER",
        "F4_ASR_WEIGHTED",
        "F5_RULE_WEIGHTED",
        "F5_RULE_WEIGHTED_CORRECTED",
        "F6_LEARNED",
    ] = "F5_RULE_WEIGHTED_CORRECTED"
    asr_variant: Literal["small", "medium"] = "medium"
    default_format: Literal["nd30_2020", "hd05_2026"] = "nd30_2020"
    use_model: bool = True


class Evaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    meeting_id: str
    transcript_version_id: str | None = None
    name: str = Field(min_length=1, max_length=200)
    reference_text: str = Field(min_length=1, max_length=100000)
    hypothesis_notes: str = Field("", max_length=2000)


class RestoreBackup(BaseModel):
    confirmation: Literal["RESTORE_TO_NEW_DATABASE"]
    artifact_id: str
