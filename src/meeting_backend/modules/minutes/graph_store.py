"""Owner-scoped graph documents, paginated independently of the exported Word file."""

from pymongo import UpdateOne

from meeting_pipeline.minutes.graph_contracts import digest


def persist_graph(mongo, meeting, graph):
    details = {
        item["unit_id"]: {
            key: item.get(key)
            for key in ("speaker", "start_sec", "end_sec", "needs_review", "turn_id", "turn_ids")
        }
        for item in graph.get("units", [])
    }
    details.update({item["event_id"]: item for item in graph.get("events", [])})
    scope = {
        "owner_id": meeting["owner_id"],
        "meeting_id": meeting["_id"],
        "graph_id": graph["graph_id"],
    }
    for key, collection in (
        ("nodes", mongo.db.meeting_graph_nodes),
        ("edges", mongo.db.meeting_graph_edges),
    ):
        operations = []
        for index, value in enumerate(graph[key]):
            identity = digest([scope, value])
            if key == "nodes":
                value = {
                    **value,
                    "attributes": {
                        **value.get("attributes", {}),
                        **details.get(value["node_id"], {}),
                    },
                }
            operations.append(
                UpdateOne(
                    {"_id": identity},
                    {
                        "$setOnInsert": {
                            **scope,
                            "index": index,
                        },
                        "$set": {"value": value},
                    },
                    upsert=True,
                )
            )
            if len(operations) >= 1000:
                collection.bulk_write(operations, ordered=False)
                operations = []
        if operations:
            collection.bulk_write(operations, ordered=False)
    mongo.db.meeting_graph_versions.update_one(
        {"_id": digest(scope)},
        {
            "$setOnInsert": {
                **scope,
                "input_sha256": graph["input_sha256"],
                "node_count": len(graph["nodes"]),
                "edge_count": mongo.db.meeting_graph_edges.count_documents(scope),
                "input_edge_count": len(graph["edges"]),
                "schema_version": graph["schema_version"],
            }
        },
        upsert=True,
    )
