"""Atomic timeline editing, explicit uncertainty and guarded processing inputs.

File IDs remain the existing ``source_ids``. Tracks and clips are layout objects,
not replacement artifact IDs. No operation in this module edits an audio file.
"""

import hashlib
import json
import math
from copy import deepcopy

from pydantic import ValidationError

from meeting_backend.core.errors import AppError
from meeting_backend.infrastructure.artifacts.store import ArtifactStore
from meeting_backend.infrastructure.mongodb.client import public
from meeting_backend.modules.meetings.repository import MeetingRepository
from meeting_backend.modules.meetings.timeline_schemas import Clip, Sequential, Timeline, Track


def fail(message, code="INVALID_TIMELINE", status=422):
    raise AppError(code, message, status)


def assets_for(mongo, meeting):
    rows = list(
        mongo.db.sources.find(
            {
                "_id": {"$in": meeting.get("source_ids", [])},
                "meeting_id": meeting["_id"],
                "owner_id": meeting["owner_id"],
            }
        )
    )
    assets = {row["_id"]: row for row in rows}
    if set(assets) != set(meeting.get("source_ids", [])):
        fail(
            "Có file không còn thuộc cuộc họp hoặc không thuộc quyền truy cập.",
            "INVALID_TIMELINE_ASSET",
        )
    return assets


def duration_ms(asset):
    duration = float(asset.get("duration_sec") or 0)
    if not math.isfinite(duration) or duration <= 0:
        fail("File chưa có thời lượng hợp lệ. Hãy kiểm tra hoặc tải lại file.")
    return math.ceil(duration * 1000 - 1e-6)


def layout_for(meeting, assets):
    if meeting.get("timeline") is not None:
        return Timeline.model_validate(meeting["timeline"]).model_dump()
    # A read does not migrate/write old meetings or invent zero offsets.
    layout = Timeline().model_dump()
    for asset_id in meeting.get("source_ids", []):
        asset = assets.get(asset_id)
        if not asset:
            fail("Có file không còn thuộc cuộc họp.", "INVALID_TIMELINE_ASSET")
        try:
            end = duration_ms(asset)
        except AppError:
            layout["unassigned_asset_ids"].append(asset_id)
            continue
        clip_id = "legacy-clip-" + asset_id
        layout["tracks"].append(
            Track(
                id="legacy-track-" + asset_id,
                name=asset["name"][:100],
                clip_ids=[clip_id],
            ).model_dump()
        )
        layout["clips"].append(
            Clip(
                id=clip_id,
                asset_id=asset_id,
                source_out_ms=end,
            ).model_dump()
        )
    return layout


def _index(items, item_id, kind):
    for item in items:
        if item["id"] == item_id:
            return item
    fail(f"Không tìm thấy {kind}.", "TIMELINE_ITEM_NOT_FOUND")


def _predecessors(layout):
    return {
        clip_id: (track["clip_ids"][index - 1] if index else None)
        for track in layout["tracks"]
        for index, clip_id in enumerate(track["clip_ids"])
    }


def _history(clip, reason):
    clip["timing_history"] = [
        *clip.get("timing_history", []),
        {"reason": reason, "placement": deepcopy(clip["placement"])},
    ][-50:]


def _user_placement(placement, predecessor):
    result = placement.model_dump()
    if result["kind"] == "anchored":
        if result["origin"] != "user" or result["status"] != "declared":
            fail("Mốc nhập tay không được tự nhận là mốc đã được âm thanh xác minh.")
    else:
        if result["origin"] not in {"unknown", "user"}:
            fail("Không thể tự xác nhận mốc nhật ký hoặc âm thanh qua thao tác sắp xếp.")
        if result["gap_before_ms"] is None:
            result.update(after_clip_id=None, origin="unknown")
        else:
            if predecessor is None:
                fail("Hãy đặt mốc bắt đầu cho đoạn đầu, thay vì khoảng cách với đoạn trước.")
            if result["after_clip_id"] not in {None, predecessor}:
                fail("Khoảng cách không khớp với đoạn đứng trước.")
            result.update(after_clip_id=predecessor, origin="user")
    return result


def resolved_positions(layout):
    clips = {clip["id"]: clip for clip in layout["clips"]}
    positions = {}
    for track in layout["tracks"]:
        previous_end = None
        for clip_id in track["clip_ids"]:
            clip = clips[clip_id]
            placement = clip["placement"]
            if placement["kind"] == "anchored":
                start = placement["start_ms"]
            elif previous_end is not None and placement["gap_before_ms"] is not None:
                start = previous_end + placement["gap_before_ms"]
            else:
                start = None
            end = None if start is None else start + clip["source_out_ms"] - clip["source_in_ms"]
            positions[clip_id] = {"start_ms": start, "end_ms": end}
            previous_end = end
    return positions


def validate(layout, assets, settings):
    layout = Timeline.model_validate(layout).model_dump()
    if len(layout["tracks"]) > settings.max_sources:
        fail("Số hàng nguồn vượt giới hạn thiết bị hiện tại.", "SOURCE_LIMIT")
    if len(layout["clips"]) > settings.max_timeline_clips:
        fail("Số đoạn timeline vượt giới hạn.", "TIMELINE_CLIP_LIMIT")
    groups = (layout["tracks"], layout["clips"], layout["intervals"])
    ids = [item["id"] for group in groups for item in group]
    if len(ids) != len(set(ids)):
        fail("Mã hàng, đoạn hoặc khoảng thời gian bị lặp.")
    clips = {clip["id"]: clip for clip in layout["clips"]}
    placed = [clip_id for track in layout["tracks"] for clip_id in track["clip_ids"]]
    if len(placed) != len(set(placed)) or set(placed) != set(clips):
        fail("Mỗi đoạn phải xuất hiện đúng một lần trên một hàng.")
    predecessors = _predecessors(layout)
    for clip in clips.values():
        asset = assets.get(clip["asset_id"])
        if not asset:
            fail("Đoạn tham chiếu file không thuộc cuộc họp.", "INVALID_TIMELINE_ASSET")
        if clip["source_out_ms"] > duration_ms(asset):
            fail("Vùng audio vượt quá thời lượng file gốc.")
        placement = clip["placement"]
        if placement["kind"] == "sequential" and placement["gap_before_ms"] is not None:
            predecessor = predecessors[clip["id"]]
            if predecessor is None or placement["after_clip_id"] != predecessor:
                fail("Khoảng cách cần gắn đúng cặp đoạn trước và sau.")
    used = {clip["asset_id"] for clip in clips.values()}
    # The pool is derived, not a second editable copy of clip assignments.
    layout["unassigned_asset_ids"] = sorted(set(assets) - used)
    for interval in layout["intervals"]:
        for field in ("start_clip_id", "end_clip_id"):
            if interval[field] is not None and interval[field] not in clips:
                fail("Khoảng thời gian tham chiếu đoạn không tồn tại.")
    positions = resolved_positions(layout)
    for track in layout["tracks"]:
        known_end = None
        for clip_id in track["clip_ids"]:
            position = positions[clip_id]
            if position["start_ms"] is not None:
                if known_end is not None and position["start_ms"] < known_end:
                    fail(
                        "Mốc thời gian các đoạn cùng nguồn bị mâu thuẫn. Hãy sửa vị trí.",
                        "TIMELINE_POSITION_CONFLICT",
                    )
                known_end = position["end_ms"]
    return layout


def content_hash(layout):
    clips = sorted(layout["clips"], key=lambda item: item["id"])
    semantic = {
        "schema_version": layout["schema_version"],
        "clock_origin": layout["clock_origin"],
        "tracks": sorted(
            [
                {"id": track["id"], "device_id": track["device_id"], "clip_ids": track["clip_ids"]}
                for track in layout["tracks"]
                if track["clip_ids"]
            ],
            key=lambda item: item["id"],
        ),
        "clips": [{k: v for k, v in clip.items() if k != "timing_history"} for clip in clips],
        "intervals": sorted(layout["intervals"], key=lambda item: item["id"]),
    }
    if layout.get("alignment_mode") == "auto":
        semantic["alignment_mode"] = "auto"
    encoded = json.dumps(semantic, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def processing_input(meeting, assets, settings, *, strict=True):
    layout = validate(layout_for(meeting, assets), assets, settings)
    blockers = []
    if not layout["clips"]:
        blockers.append("Hãy đặt ít nhất một file lên hàng nguồn trước khi xử lý.")
    if layout["unassigned_asset_ids"]:
        blockers.append("Có file chưa được xếp. Hãy đặt lên timeline hoặc bỏ khỏi cuộc họp.")
    legacy = layout.get("alignment_mode", "legacy") == "legacy" and all(
        len(track["clip_ids"]) <= 1 for track in layout["tracks"]
    )
    for clip in layout["clips"]:
        if (
            clip["source_in_ms"] != 0
            or clip["source_out_ms"] != duration_ms(assets[clip["asset_id"]])
            or clip["placement"]["kind"] != "sequential"
            or clip["placement"]["gap_before_ms"] is not None
        ):
            legacy = False
    if layout["intervals"]:
        legacy = False
    asset_ids = sorted({clip["asset_id"] for clip in layout["clips"]})
    if len(asset_ids) != len(layout["clips"]):
        legacy = False
    result = {
        "supported": not blockers,
        "mode": (
            "pending_timeline_processing" if blockers else "legacy_auto" if legacy else "timeline"
        ),
        "blockers": blockers,
        "source_ids": asset_ids,
        "timeline": layout,
        "timeline_hash": content_hash(layout),
    }
    if strict and blockers:
        fail(blockers[0], "TIMELINE_PROCESSING_NOT_READY", 409)
    return result


def view(mongo, meeting):
    assets = assets_for(mongo, meeting)
    layout = validate(layout_for(meeting, assets), assets, mongo.settings)
    store = ArtifactStore(mongo)
    files = []
    for asset_id in meeting.get("source_ids", []):
        asset = assets.get(asset_id)
        if not asset:
            continue
        artifact = mongo.db.artifacts.find_one(
            {
                "_id": asset["artifact_id"],
                "owner_id": meeting["owner_id"],
            }
        )
        files.append({**public(asset), "artifact": store.view(artifact) if artifact else None})
    readiness = processing_input(meeting, assets, mongo.settings, strict=False)
    return {
        "revision": meeting["revision"],
        "content_revision": meeting.get("content_revision", 0),
        "legacy": meeting.get("timeline") is None,
        "timeline": layout,
        "timeline_hash": content_hash(layout),
        "resolved_positions": resolved_positions(layout),
        "assets": files,
        "processing": {k: readiness[k] for k in ("supported", "mode", "blockers")},
        "last_alignment": meeting.get("processing_summary", {}).get("alignment"),
        "alignment_stale": bool(meeting.get("processing_summary", {}).get("alignment"))
        and (
            meeting.get("state") == "draft"
            or meeting.get("processing_summary", {}).get("input_timeline_hash")
            != content_hash(layout)
        ),
    }


def _insert(track, clip_id, before_clip_id):
    if before_clip_id is None:
        track["clip_ids"].append(clip_id)
    elif before_clip_id in track["clip_ids"]:
        track["clip_ids"].insert(track["clip_ids"].index(before_clip_id), clip_id)
    else:
        fail("Đoạn đích không nằm trên hàng đã chọn.")


def apply_operations(layout, operations, assets, settings):
    layout = deepcopy(layout)
    for operation in operations:
        op = operation.model_dump()
        kind = op["op"]
        if kind in {
            "add_clip",
            "move_clip",
            "set_placement",
            "set_range",
            "upsert_interval",
            "remove_interval",
            "set_clock_origin",
            "remove_clip",
        }:
            layout["alignment_mode"] = "auto"
        old_predecessors = _predecessors(layout)
        explicit_placement = set()
        if kind == "create_track":
            layout["tracks"].append(
                Track(
                    id=op["id"],
                    name=op["name"].strip(),
                    device_id=op["device_id"],
                ).model_dump()
            )
        elif kind == "update_track":
            track = _index(layout["tracks"], op["track_id"], "hàng nguồn")
            track["name"] = op["name"].strip()
            if "device_id" in operation.model_fields_set:
                track["device_id"] = op["device_id"]
        elif kind == "reorder_tracks":
            if len(set(op["track_ids"])) != len(op["track_ids"]) or set(op["track_ids"]) != {
                track["id"] for track in layout["tracks"]
            }:
                fail("Thứ tự hàng phải chứa đúng các hàng hiện có.")
            layout["tracks"] = [
                _index(layout["tracks"], item, "hàng nguồn") for item in op["track_ids"]
            ]
        elif kind == "remove_track":
            track = _index(layout["tracks"], op["track_id"], "hàng nguồn")
            if track["clip_ids"]:
                fail("Hãy chuyển hoặc bỏ các đoạn trước khi xóa hàng.")
            layout["tracks"].remove(track)
        elif kind == "add_clip":
            asset = assets.get(op["asset_id"])
            if not asset:
                fail("File không thuộc cuộc họp.", "INVALID_TIMELINE_ASSET")
            track = _index(layout["tracks"], op["track_id"], "hàng nguồn")
            _insert(track, op["id"], op["before_clip_id"])
            predecessor = _predecessors(layout)[op["id"]]
            layout["clips"].append(
                Clip(
                    id=op["id"],
                    asset_id=op["asset_id"],
                    source_in_ms=op["source_in_ms"],
                    source_out_ms=(
                        op["source_out_ms"]
                        if op["source_out_ms"] is not None
                        else duration_ms(asset)
                    ),
                    placement=_user_placement(operation.placement, predecessor),
                ).model_dump()
            )
            explicit_placement.add(op["id"])
        elif kind == "move_clip":
            clip = _index(layout["clips"], op["clip_id"], "đoạn audio")
            target = _index(layout["tracks"], op["track_id"], "hàng nguồn")
            if op["before_clip_id"] == clip["id"]:
                fail("Không thể đặt đoạn trước chính nó.")
            for track in layout["tracks"]:
                if clip["id"] in track["clip_ids"]:
                    track["clip_ids"].remove(clip["id"])
            _insert(target, clip["id"], op["before_clip_id"])
            if operation.placement is not None:
                _history(clip, "user_moved")
                clip["placement"] = _user_placement(
                    operation.placement,
                    _predecessors(layout)[clip["id"]],
                )
                explicit_placement.add(clip["id"])
        elif kind == "set_placement":
            clip = _index(layout["clips"], op["clip_id"], "đoạn audio")
            _history(clip, "user_set_placement")
            clip["placement"] = _user_placement(
                operation.placement,
                _predecessors(layout)[clip["id"]],
            )
            explicit_placement.add(clip["id"])
        elif kind == "set_range":
            clip = _index(layout["clips"], op["clip_id"], "đoạn audio")
            clip.update(source_in_ms=op["source_in_ms"], source_out_ms=op["source_out_ms"])
        elif kind == "remove_clip":
            clip = _index(layout["clips"], op["clip_id"], "đoạn audio")
            if any(
                clip["id"] in (item["start_clip_id"], item["end_clip_id"])
                for item in layout["intervals"]
            ):
                fail("Hãy cập nhật khoảng thời gian đang tham chiếu đoạn này trước.")
            layout["clips"].remove(clip)
            for track in layout["tracks"]:
                if clip["id"] in track["clip_ids"]:
                    track["clip_ids"].remove(clip["id"])
        elif kind == "upsert_interval":
            layout["intervals"] = [
                item for item in layout["intervals"] if item["id"] != op["interval"]["id"]
            ]
            layout["intervals"].append(op["interval"])
        elif kind == "remove_interval":
            interval = _index(layout["intervals"], op["interval_id"], "khoảng thời gian")
            layout["intervals"].remove(interval)
        elif kind == "set_clock_origin":
            value = op["value"]
            if value is not None and (value["origin"] != "user" or value["status"] != "declared"):
                fail("Giờ nhập tay chỉ được ghi là mốc do người dùng khai báo.")
            layout["clock_origin"] = value
        # A known gap belongs to its old pair, never to the new predecessor.
        new_predecessors = _predecessors(layout)
        for clip in layout["clips"]:
            placement = clip["placement"]
            if (
                placement["kind"] == "sequential"
                and placement["gap_before_ms"] is not None
                and clip["id"] not in explicit_placement
                and old_predecessors.get(clip["id"]) != new_predecessors.get(clip["id"])
            ):
                _history(clip, "predecessor_changed")
                clip["placement"] = Sequential().model_dump()
    return validate(layout, assets, settings)


def patch(mongo, user, meeting_id, payload):
    repo = MeetingRepository(mongo)
    meeting = repo.editable(meeting_id, user, payload.revision)
    assets = assets_for(mongo, meeting)
    before = validate(layout_for(meeting, assets), assets, mongo.settings)
    try:
        after = apply_operations(before, payload.operations, assets, mongo.settings)
    except ValidationError as exc:
        raise AppError("INVALID_TIMELINE", "Bố cục hoặc vùng audio không hợp lệ.", 422) from exc
    changed = content_hash(before) != content_hash(after)
    changes = {"timeline": after}
    if changed:
        changes.update(state="draft", transcript_stale=bool(meeting.get("active_transcript_id")))
    result = repo.update(meeting, changes, content_changed=changed)

    def states(layout):
        owners = {
            clip_id: track["id"] for track in layout["tracks"] for clip_id in track["clip_ids"]
        }
        return {
            clip["id"]: {
                **{key: value for key, value in clip.items() if key != "timing_history"},
                "track_id": owners[clip["id"]],
            }
            for clip in layout["clips"]
        }

    old_states, new_states = states(before), states(after)
    clip_changes = [
        {
            "clip_id": clip_id,
            "before": old_states.get(clip_id),
            "after": new_states.get(clip_id),
        }
        for clip_id in sorted(set(old_states) | set(new_states))
        if old_states.get(clip_id) != new_states.get(clip_id)
    ]
    mongo.audit(
        user["_id"],
        "timeline_updated",
        meeting_id,
        operations=[op.op for op in payload.operations],
        content_changed=changed,
        previous_timeline_hash=content_hash(before),
        timeline_hash=content_hash(after),
        clip_changes=clip_changes,
        previous_clock_origin=before["clock_origin"],
        clock_origin=after["clock_origin"],
    )
    return view(mongo, result)


def append_assets(meeting, assets, created, settings, *, track_id=None, timeline_mode=False):
    """Preserve old uploads; new timeline uploads target a track or the unplaced pool."""
    if meeting.get("timeline") is None and not timeline_mode and track_id is None:
        return None
    layout = layout_for(meeting, assets)
    if timeline_mode or track_id is not None:
        layout["alignment_mode"] = "auto"
    combined = {**assets, **{asset["_id"]: asset for asset in created}}
    if track_id is not None:
        track = _index(layout["tracks"], track_id, "hàng nguồn")
        for asset in created:
            clip_id = "clip-" + asset["_id"]
            track["clip_ids"].append(clip_id)
            layout["clips"].append(
                Clip(
                    id=clip_id,
                    asset_id=asset["_id"],
                    source_out_ms=duration_ms(asset),
                ).model_dump()
            )
    return validate(layout, combined, settings)
