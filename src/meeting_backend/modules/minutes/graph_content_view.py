"""A readable projection of event/topic relationships; raw evidence stays in the inspector."""

from meeting_backend.core.errors import AppError
from meeting_pipeline.minutes.graph_editorial import STRUCTURAL_ROLES

CONTEXT_KINDS = [
    "meeting",
    "session",
    "episode",
    "person",
    "actor",
    "document_version",
    "evidence",
    "filler",
]
TECHNICAL_EDGES = [
    "contains",
    "next",
    "evidenced_by",
    "spoken_by",
    "assigned_to",
    "applies_to_version",
    "about",
]


def content_view(mongo, scope, node_id, page, limit):
    nodes, edges = mongo.db.meeting_graph_nodes, mongo.db.meeting_graph_edges
    limit = min(limit, 12) if node_id else min(limit, 40)
    focus = nodes.find_one({**scope, "value.node_id": node_id}) if node_id else None
    if node_id and not focus:
        raise AppError("GRAPH_NODE_NOT_FOUND", "Không tìm thấy nút trong đồ thị này.", 404)
    truncated = False
    if not focus:
        query = {
            **scope,
            "value.kind": {"$in": ["topic", "topic_group"]},
            "value.attributes.procedural_role": {"$nin": list(STRUCTURAL_ROLES)},
        }
    elif focus["value"]["kind"] == "topic_group":
        children = edges.find({**scope, "value.source": node_id, "value.kind": "contains"})
        query = {**scope, "value.node_id": {"$in": [row["value"]["target"] for row in children]}}
    elif focus["value"]["kind"] == "topic":
        query = {
            **scope,
            "value.attributes.primary_topic": node_id,
            "value.kind": {"$nin": CONTEXT_KINDS},
            "value.attributes.editorial_role": {"$nin": list(STRUCTURAL_ROLES)},
        }
        if not nodes.count_documents(
            {**scope, "value.attributes.primary_topic": {"$exists": True}}
        ):
            # Old graph versions have no primary_topic attribute. Read their stored
            # topic/evidence paths without rewriting immutable historical graphs.
            links = list(
                edges.find({**scope, "value.target": node_id, "value.kind": "about"})
                .sort("index", 1)
                .skip((page - 1) * limit)
                .limit(limit)
            )
            evidence = [row["value"]["source"] for row in links]
            citations = list(
                edges.find(
                    {**scope, "value.target": {"$in": evidence}, "value.kind": "evidenced_by"}
                ).limit(200)
            )
            ids = [row["value"]["source"] for row in citations]
            query = {**scope, "value.node_id": {"$in": ids}, "value.kind": {"$nin": CONTEXT_KINDS}}
            total = edges.count_documents({**scope, "value.target": node_id, "value.kind": "about"})
            selected = list(nodes.find(query).sort("index", 1).limit(limit))
            for row in selected:
                row["value"] = {
                    **row["value"],
                    "attributes": {
                        **row["value"].get("attributes", {}),
                        "primary_topic": node_id,
                    },
                }
            return _finish(scope, nodes, edges, focus, selected, total, page, limit, False)
    else:
        query_edges = {
            **scope,
            "value.kind": {"$nin": TECHNICAL_EDGES},
            "$or": [{"value.source": node_id}, {"value.target": node_id}],
        }
        links = list(edges.find(query_edges).sort("index", 1).limit(101))
        ids = {
            end for row in links[:100] for end in (row["value"]["source"], row["value"]["target"])
        } - {node_id}
        query = {
            **scope,
            "value.node_id": {"$in": sorted(ids)},
            "value.kind": {"$nin": CONTEXT_KINDS},
        }
        truncated = len(links) > 100
    total = nodes.count_documents(query)
    selected = list(
        nodes.find(query)
        .sort([("value.attributes.presentation_priority", 1), ("index", 1)])
        .skip((page - 1) * limit)
        .limit(limit)
    )
    return _finish(scope, nodes, edges, focus, selected, total, page, limit, truncated)


def _finish(scope, nodes, edges, focus, selected, total, page, limit, truncated):
    values = [row["value"] for row in selected]
    if focus:
        values.insert(0, focus["value"])
    ids = {row["node_id"] for row in values}
    visible_edges = [
        row["value"]
        for row in edges.find(
            {
                **scope,
                "value.source": {"$in": sorted(ids)},
                "value.target": {"$in": sorted(ids)},
                "value.kind": {"$nin": TECHNICAL_EDGES},
            }
        )
        .sort("index", 1)
        .limit(81)
    ]
    truncated |= len(visible_edges) > 80
    visible_edges = visible_edges[:80]
    groups = [row["node_id"] for row in values if row["kind"] == "topic_group"]
    if groups:
        visible_edges.extend(
            row["value"]
            for row in edges.find(
                {
                    **scope,
                    "value.source": {"$in": groups},
                    "value.target": {"$in": sorted(ids)},
                    "value.kind": "contains",
                }
            ).limit(40)
        )
    topics = {
        row["attributes"].get("primary_topic")
        for row in values
        if row.get("attributes", {}).get("primary_topic")
    }
    for row in nodes.find({**scope, "value.node_id": {"$in": sorted(topics)}}).limit(12):
        if row["value"]["node_id"] not in ids:
            values.append(row["value"])
            ids.add(row["value"]["node_id"])
    for row in values:
        attributes = row.get("attributes", {})
        topic = attributes.get("primary_topic")
        if topic and topic in ids and row["node_id"] != topic:
            visible_edges.append(
                {
                    "source": row["node_id"],
                    "target": topic,
                    "kind": "about",
                    "evidence_ids": attributes.get("unit_ids", []),
                    "asserted": False,
                    "projection": True,
                }
            )
    return {
        "nodes": values,
        "edges": visible_edges,
        "focus_id": focus["value"]["node_id"] if focus else None,
        "page": page,
        "limit": limit,
        "total": total,
        "has_more": page * limit < total,
        "truncated": truncated,
        "mode": "content",
    }
