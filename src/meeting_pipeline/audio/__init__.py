"""Audio processing, multi-source synchronization and VAD segmentation."""

from meeting_pipeline.audio.synchronization import (
    extract_shared_meeting_segments,
    select_reference_source,
    synchronize_multi_source_audio,
)

__all__ = [
    "extract_shared_meeting_segments",
    "select_reference_source",
    "synchronize_multi_source_audio",
]
