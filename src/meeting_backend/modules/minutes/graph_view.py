"""Bounded, owner-scoped graph views for interactive exploration."""

from meeting_backend.core.errors import AppError

OVERVIEW_KINDS = ["meeting", "session", "topic_group", "topic"]
DETAIL_KINDS = ["evidenced_by", "spoken_by", "assigned_to", "about", "applies_to_version"]
MAX_NODES = 200
MAX_EDGES = 600


def graph_view(mongo, scope, node_id, page, limit):
    nodes, edges = mongo.db.meeting_graph_nodes, mongo.db.meeting_graph_edges
    truncated = False
    if node_id:
        focus = nodes.find_one({**scope, "value.node_id": node_id})
        if not focus:
            raise AppError("GRAPH_NODE_NOT_FOUND", "Không tìm thấy nút trong đồ thị này.", 404)
        query = {**scope, "$or": [{"value.source": node_id}, {"value.target": node_id}]}
        total = edges.count_documents(query)
        primary = list(edges.find(query).sort("index", 1).skip((page - 1) * limit).limit(limit))
        ids = {node_id}
        for edge in primary:
            ids.update([edge["value"]["source"], edge["value"]["target"]])
        # One bounded expansion connects a topic's transcript units to their events,
        # or an event to its transcript/topic. Never download the entire graph.
        expandable = [
            row["value"]["node_id"]
            for row in nodes.find(
                {
                    **scope,
                    "value.node_id": {"$in": sorted(ids - {node_id})},
                    "value.kind": {
                        "$nin": [*OVERVIEW_KINDS, "episode", "person", "actor", "document_version"]
                    },
                }
            )
        ]
        expansion_query = {
            **scope,
            "value.kind": {"$in": DETAIL_KINDS},
            "$or": [{"value.source": {"$in": expandable}}, {"value.target": {"$in": expandable}}],
        }
        expansion = list(edges.find(expansion_query).sort("index", 1).limit(MAX_EDGES + 1))
        truncated = len(expansion) > MAX_EDGES
        for row in expansion[:MAX_EDGES]:
            for key in ("source", "target"):
                candidate = row["value"][key]
                if candidate not in ids:
                    if len(ids) < MAX_NODES:
                        ids.add(candidate)
                    else:
                        truncated = True
        selected = list(
            nodes.find({**scope, "value.node_id": {"$in": sorted(ids)}}).sort("index", 1)
        )
    else:
        query = {**scope, "value.kind": {"$in": OVERVIEW_KINDS}}
        total = nodes.count_documents(query)
        selected = list(nodes.find(query).sort("index", 1).skip((page - 1) * limit).limit(limit))
    visible = [row["value"]["node_id"] for row in selected]
    edge_query = {**scope, "value.source": {"$in": visible}, "value.target": {"$in": visible}}
    connections = list(edges.find(edge_query).sort("index", 1).limit(MAX_EDGES + 1))
    return {
        "nodes": [row["value"] for row in selected],
        "edges": [row["value"] for row in connections[:MAX_EDGES]],
        "focus_id": node_id or None,
        "page": page,
        "limit": limit,
        "total": total,
        "has_more": page * limit < total,
        "truncated": truncated or len(connections) > MAX_EDGES,
    }
