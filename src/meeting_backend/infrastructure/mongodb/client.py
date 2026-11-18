"""MongoDB connection, dedicated collections and initial schema/index migration."""

from datetime import UTC, datetime
from uuid import uuid4

from pymongo import ASCENDING, MongoClient
from pymongo.errors import CollectionInvalid

from meeting_backend.core.settings import Settings

COLLECTIONS = (
    "users",
    "sessions",
    "meetings",
    "sources",
    "speakers",
    "templates",
    "jobs",
    "transcript_versions",
    "transcript_segments",
    "template_versions",
    "minutes_versions",
    "minutes_input_snapshots",
    "minutes_input_segments",
    "style_profiles",
    "style_learning_audit",
    "meeting_graph_versions",
    "meeting_graph_nodes",
    "meeting_graph_edges",
    "meeting_outline_sections",
    "meeting_outline_items",
    "artifacts",
    "audit_events",
    "settings",
    "schema_migrations",
    "experiments",
)


def now() -> str:
    return datetime.now(UTC).isoformat()


def new_id() -> str:
    return str(uuid4())


def public(record):
    if record is None:
        return None
    return {
        ("id" if key == "_id" else key): value
        for key, value in record.items()
        if key not in {"password_hash", "token_hash", "csrf_hash", "path"}
        and not key.endswith("_path")
    }


class Mongo:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=3000, tz_aware=True)
        self.db = self.client[settings.mongo_database]

    def initialize(self):
        self.client.admin.command("ping")
        existing = set(self.db.list_collection_names())
        for name in COLLECTIONS:
            if name not in existing:
                try:
                    self.db.create_collection(
                        name,
                        validator={
                            "$jsonSchema": {
                                "bsonType": "object",
                                "required": ["_id"],
                                "properties": {"_id": {"bsonType": "string"}},
                            }
                        },
                    )
                except CollectionInvalid:
                    pass
        # A database must never silently point to another checkout's artifact directory.
        root = str(self.settings.data_dir.resolve())
        binding = self.db.settings.find_one_and_update(
            {"_id": "storage_binding"},
            {"$setOnInsert": {"data_root": root}},
            upsert=True,
            return_document=True,
        )
        if binding["data_root"] != root:
            raise RuntimeError(
                "Database đã gắn với thư mục dữ liệu khác. Chọn database riêng "
                "hoặc đúng MEETING_APP_DATA_DIR."
            )
        self.db.users.create_index("username", unique=True)
        self.db.sessions.create_index("token_hash", unique=True)
        self.db.sessions.create_index("expires_at", expireAfterSeconds=0)
        self.db.transcript_segments.create_index([("version_id", 1), ("index", 1)], unique=True)
        self.db.transcript_segments.create_index([("version_id", 1), ("needs_review", 1)])
        self.db.jobs.create_index([("state", 1), ("created_at", 1)])
        self.db.jobs.create_index("lease_until")
        self.db.minutes_input_segments.create_index(
            [("snapshot_id", 1), ("owner_id", 1), ("index", 1)], unique=True
        )
        self.db.style_profiles.create_index("owner_id", unique=True)
        for graph_collection in (self.db.meeting_graph_nodes, self.db.meeting_graph_edges):
            graph_collection.create_index(
                [("owner_id", 1), ("meeting_id", 1), ("graph_id", 1), ("index", 1)]
            )
        graph_scope_keys = [("owner_id", 1), ("meeting_id", 1), ("graph_id", 1)]
        self.db.meeting_graph_nodes.create_index([*graph_scope_keys, ("value.node_id", 1)])
        self.db.meeting_graph_nodes.create_index(
            [*graph_scope_keys, ("value.kind", 1), ("index", 1)]
        )
        for endpoint in ("source", "target"):
            self.db.meeting_graph_edges.create_index(
                [*graph_scope_keys, (f"value.{endpoint}", 1), ("index", 1)]
            )
        outline_keys = [("owner_id", 1), ("meeting_id", 1), ("version_id", 1)]
        self.db.meeting_outline_sections.create_index([*outline_keys, ("index", 1)])
        self.db.meeting_outline_items.create_index(
            [*outline_keys, ("section_id", 1), ("index", 1)]
        )
        for name in ["meetings", "templates", "speakers", "jobs", "audit_events", "experiments"]:
            self.db[name].create_index([("owner_id", ASCENDING), ("created_at", -1)])
        self.db.artifacts.create_index("path", unique=True)
        self.db.schema_migrations.update_one(
            {"_id": "001_initial"},
            {
                "$setOnInsert": {
                    "applied_at": now(),
                    "description": "Collections, validation and indexes",
                }
            },
            upsert=True,
        )

    def audit(self, actor_id: str, action: str, resource_id: str, **details):
        self.db.audit_events.insert_one(
            {
                "_id": new_id(),
                "owner_id": actor_id,
                "action": action,
                "resource_id": resource_id,
                "details": details,
                "created_at": now(),
            }
        )

    def close(self):
        self.client.close()
