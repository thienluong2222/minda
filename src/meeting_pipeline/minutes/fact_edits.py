"""Merge reviewed fields without discarding their provenance or changing untouched facts."""

from __future__ import annotations

from typing import Any

from meeting_pipeline.minutes.schemas import MeetingFact


def merge_fact_edits(
    current: list[MeetingFact], patches: list[dict[str, Any]], *, mark_user_edited: bool = True
) -> list[MeetingFact]:
    """Apply explicit changes by ID; no-op saves preserve types, evidence and timestamps."""
    by_id = {fact.field_id: fact for fact in current}
    seen: set[str] = set()
    for patch in patches:
        field_id = patch.get("field_id")
        if not isinstance(field_id, str) or field_id not in by_id or field_id in seen:
            raise ValueError("Trường biên bản không tồn tại hoặc bị lặp.")
        seen.add(field_id)
        original = by_id[field_id]
        changes = {
            key: value
            for key, value in patch.items()
            if key in {"value", "status", "reason"} and value != getattr(original, key)
        }
        if not changes:
            continue
        if "value" in changes and "status" not in changes:
            changes["status"] = "needs_review" if changes["value"] else "unknown"
        merged = {**original.model_dump(), **changes}
        if mark_user_edited:
            merged["user_edited"] = True
            merged["transcript_revision"] = original.transcript_revision + 1
            merged.pop("updated_at", None)
        by_id[field_id] = MeetingFact.model_validate(merged)
    return [by_id[fact.field_id] for fact in current]
