"""Speaker enrollment and identification package."""

from meeting_pipeline.speaker.encoder import ECAPAEncoder
from meeting_pipeline.speaker.enrollment import build_speaker_prototypes
from meeting_pipeline.speaker.identification import identify_multi_source_speaker

__all__ = [
    "ECAPAEncoder",
    "build_speaker_prototypes",
    "identify_multi_source_speaker",
]
