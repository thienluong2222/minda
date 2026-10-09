"""Distinguish a person's identity from timeline state labels."""

from __future__ import annotations

import unicodedata


def normalize_speaker_label(label: str) -> str:
    return " ".join(unicodedata.normalize("NFC", label).split())


def person_identity_key(
    label: str,
    speaker_id: str | None = None,
    meeting_speaker_id: str | None = None,
    speaker_status: str = "",
    speaker_count: int = 1,
    overlap_group_id: str | None = None,
) -> tuple[str, str] | None:
    """Use stable IDs for people; never turn uncertainty/overlap into attendees.

    Legacy timelines without status or IDs can still use a real display name.
    Anonymous clusters with an ordinal remain distinct people awaiting identity review.
    """
    normalized = normalize_speaker_label(label).casefold()
    if (
        not normalized
        or speaker_count != 1
        or overlap_group_id
        or speaker_status in {"ambiguous", "unresolved", "overlap"}
        or normalized in {"unknown", "unidentified", "anonymous", "người lạ", "speaker"}
        or normalized.startswith(("chưa xác định", "chưa rõ", "nói chồng", "overlap"))
    ):
        return None
    if speaker_id and speaker_id.casefold() not in {"unknown", "unidentified", "anonymous"}:
        return "speaker", speaker_id
    if meeting_speaker_id:
        return "meeting", meeting_speaker_id
    return "label", normalized
