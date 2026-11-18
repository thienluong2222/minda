"""Editable content plans pinned to a graph and transcript revision."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from meeting_pipeline.minutes.graph_contracts import MeetingGraph, Section, StrictModel, digest


class PlannedItemEdit(StrictModel):
    item_id: str
    priority: Literal["required", "optional"]
    included: bool


class PlannedSectionEdit(StrictModel):
    section_id: str
    title: str = Field(min_length=1, max_length=160)
    items: list[PlannedItemEdit] = Field(max_length=50000)


class ContentPlan(StrictModel):
    schema_version: Literal["3.0"] = "3.0"
    phase: Literal["prepared", "written"] = "prepared"
    graph_id: str
    transcript_version_id: str | None = None
    plan_id: str = ""
    parent_plan_id: str | None = None
    sections: list[Section]
    ledger: list[dict[str, Any]]
    review_items: list[dict[str, Any]] = Field(default_factory=list)

    def seal(self) -> None:
        self.plan_id = (
            "p_"
            + digest(
                [
                    self.graph_id,
                    self.transcript_version_id,
                    self.parent_plan_id,
                    [section.model_dump(exclude={"paragraphs"}) for section in self.sections],
                    self.ledger,
                ]
            )[:20]
        )

    def prepared(self) -> dict:
        return {
            **self.model_dump(exclude={"sections"}),
            "phase": "prepared",
            "sections": [{**section.model_dump(), "paragraphs": []} for section in self.sections],
        }


def revise_plan(
    base: ContentPlan, graph: MeetingGraph, edits: list[PlannedSectionEdit]
) -> tuple[ContentPlan, set[str]]:
    if base.graph_id != graph.graph_id or base.transcript_version_id != graph.metadata.get(
        "transcript_version_id"
    ):
        raise ValueError("Dàn ý không còn khớp với đồ thị hoặc lời chép.")
    previous = {section.section_id: section for section in base.sections}
    edited_ids = [section.section_id for section in edits]
    if len(set(edited_ids)) != len(edits) or set(edited_ids) != previous.keys():
        raise ValueError("Danh sách mục dàn ý bị thiếu, thừa hoặc lặp.")

    items = {item.item_id: item for section in base.sections for item in section.outline}
    item_ids = [item.item_id for section in edits for item in section.items]
    if len(set(item_ids)) != len(item_ids) or set(item_ids) != items.keys():
        raise ValueError("Mỗi ý phải xuất hiện một lần trong dàn ý.")
    if any(
        item.priority == "required" and not item.included
        for section in edits
        for item in section.items
    ):
        raise ValueError("Ý bị lược cần được đánh dấu là có thể lược.")

    plan = base.model_copy(deep=True, update={"parent_plan_id": base.plan_id, "phase": "prepared"})
    ledger = {row["claim_id"]: row for row in plan.ledger}
    primary_topics = {
        node.node_id: node.attributes.get("primary_topic")
        for node in graph.nodes
        if node.attributes.get("primary_topic")
    }
    plan.sections = []
    changed = set()
    for edit in edits:
        prior = previous[edit.section_id]
        section = prior.model_copy(deep=True)
        title = " ".join(edit.title.split())
        if not title:
            raise ValueError("Hãy nhập tên mục.")
        section.title = title
        section.title_edited = prior.title_edited or title != prior.title
        section.outline = [
            items[item.item_id].model_copy(
                update={"included": item.included, "priority": item.priority}
            )
            for item in edit.items
        ]
        if title != prior.title or section.outline != prior.outline:
            changed.add(section.section_id)
            section.paragraphs = []
        section.claim_ids = [item.item_id for item in section.outline if item.included]
        section.claim_groups = {
            item.item_id: item.claim_ids[1:]
            for item in section.outline
            if item.included and len(item.claim_ids) > 1
        }
        for item in section.outline:
            for cid in item.claim_ids:
                ledger[cid]["section_id"] = section.section_id
                ledger[cid]["priority"] = item.priority
                ledger[cid]["disposition"] = (
                    "context_only"
                    if not item.included
                    else "included"
                    if cid == item.item_id
                    else "merged"
                )
                if not item.included:
                    ledger[cid]["reason"] = "outline_edit"
                elif ledger[cid].get("reason") == "outline_edit":
                    ledger[cid].pop("reason")
        if {item.item_id for item in prior.outline} != {item.item_id for item in section.outline}:
            section.topic_ids = list(
                dict.fromkeys(
                    primary_topics[cid] for cid in section.claim_ids if cid in primary_topics
                )
            )
            section.topic_id = section.topic_ids[0] if len(section.topic_ids) == 1 else None
            section.summary = ""
        plan.sections.append(section)
    plan.seal()
    return plan, changed
