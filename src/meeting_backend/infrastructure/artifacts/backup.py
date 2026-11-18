"""Portable snapshots with checksums; restore always targets a new database and directory."""

import hashlib
import json
import shutil
import zipfile
from pathlib import Path, PurePosixPath

from bson import json_util

from meeting_backend.core.errors import AppError
from meeting_backend.infrastructure.mongodb.client import COLLECTIONS, Mongo, new_id, now

EXCLUDED = {"sessions", "jobs"}


def rewrite(value, old_root, new_root):
    if isinstance(value, str):
        return (
            value.replace(old_root + "/", new_root + "/")
            if value.startswith(old_root + "/")
            else value
        )
    if isinstance(value, list):
        return [rewrite(item, old_root, new_root) for item in value]
    if isinstance(value, dict):
        return {key: rewrite(item, old_root, new_root) for key, item in value.items()}
    return value


def run_backup(context):
    if context.job["kind"] == "restore_system":
        return restore(context)
    context.stage("Chụp metadata và các phiên bản tài liệu bất biến")
    if context.mongo.db.jobs.count_documents(
        {"state": "running", "_id": {"$ne": context.job["_id"]}}
    ):
        raise AppError("SYSTEM_BUSY", "Hãy đợi các tác vụ đang chạy kết thúc rồi sao lưu.", 409)
    records = {
        name: list(context.mongo.db[name].find()) for name in COLLECTIONS if name not in EXCLUDED
    }
    records["settings"] = [row for row in records["settings"] if row["_id"] == "processing_preset"]
    for rows in records.values():
        for row in rows:
            if "active_job" in row:
                row["active_job"] = None
    # Copy all referenced run directories too: adapters need schemas and sidecar JSON when editing.
    files = set()
    for artifact in records["artifacts"]:
        path = context.store.resolve(artifact)
        if not str(artifact["path"]).startswith(("backups/", "restores/")):
            files.add(path)
    for name in ["minutes_versions", "transcript_versions"]:
        for row in records[name]:
            if row.get("run_path"):
                directory = Path(row["run_path"]).resolve()
                if not directory.is_relative_to(context.store.root):
                    raise AppError("INVALID_PATH", "Phiên bản nằm ngoài kho dữ liệu.")
                files.update(p for p in directory.rglob("*") if p.is_file())
    voice_dir = context.root / "voices"
    if voice_dir.is_dir():
        files.update(p for p in voice_dir.rglob("*") if p.is_file())
    records["artifacts"] = [a for a in records["artifacts"] if context.store.resolve(a) in files]
    destination = context.root / "backups" / (context.job["_id"] + ".zip")
    destination.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "format": "meeting-app-backup-v1",
        "created_at": now(),
        "database": context.mongo.settings.mongo_database,
        "data_root": str(context.root),
        "excluded": ["sessions", "jobs", "model_cache", "logs"],
        "files": {},
    }
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        metadata = json_util.dumps(records).encode()
        archive.writestr("metadata.json", metadata)
        manifest["metadata_sha256"] = hashlib.sha256(metadata).hexdigest()
        for index, path in enumerate(sorted(files)):
            if index % 20 == 0:
                context.stage(f"Đóng gói file {index + 1}/{len(files)}")
            name = "files/" + path.relative_to(context.store.root).as_posix()
            digest = hashlib.sha256()
            size = 0
            with path.open("rb") as source, archive.open(name, "w", force_zip64=True) as output:
                while chunk := source.read(1024 * 1024):
                    context.check()
                    digest.update(chunk)
                    size += len(chunk)
                    output.write(chunk)
            manifest["files"][name] = {
                "sha256": digest.hexdigest(),
                "size": size,
            }
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
    artifact = context.artifact(destination, name="meeting-backup-" + now()[:10] + ".zip")
    context.publish({}, result={"backup": artifact, "file_count": len(files)})


def restore(context):
    context.stage("Kiểm tra cấu trúc và checksum bản sao lưu")
    artifact = context.mongo.db.artifacts.find_one(
        {"_id": context.job["payload"]["artifact_id"], "owner_id": context.job["owner_id"]}
    )
    if not artifact:
        raise AppError("NOT_FOUND", "Không tìm thấy bản sao lưu.", 404)
    restore_id = new_id().replace("-", "")
    database = "meeting_app_restore_" + restore_id
    destination = context.root / "restores" / restore_id
    target = None
    created = False
    try:
        with zipfile.ZipFile(context.store.resolve(artifact)) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or len(names) > 100000:
                raise ValueError("Số lượng hoặc tên file ZIP không hợp lệ.")
            if sum(i.file_size for i in archive.infolist()) > 20_000_000_000:
                raise ValueError("Bản sao lưu vượt giới hạn giải nén 20 GB.")
            for name in names:
                path = PurePosixPath(name)
                if path.is_absolute() or ".." in path.parts or "\\" in name:
                    raise ValueError("ZIP có đường dẫn không an toàn.")
            if (
                archive.getinfo("manifest.json").file_size > 20_000_000
                or archive.getinfo("metadata.json").file_size > 50_000_000
            ):
                raise ValueError("Manifest hoặc metadata vượt giới hạn kích thước.")
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("format") != "meeting-app-backup-v1":
                raise ValueError("Không hỗ trợ định dạng bản sao lưu.")
            metadata = archive.read("metadata.json")
            if hashlib.sha256(metadata).hexdigest() != manifest["metadata_sha256"]:
                raise ValueError("Checksum metadata không khớp.")
            records = json_util.loads(metadata)
            if set(records) - set(COLLECTIONS) or EXCLUDED.intersection(records):
                raise ValueError("Collection không được phép trong bản sao lưu.")
            for index, (name, expected) in enumerate(manifest["files"].items()):
                if not name.startswith("files/") or name not in names:
                    raise ValueError("File trong manifest không hợp lệ.")
                path = (destination / name[6:]).resolve()
                if not path.is_relative_to(destination.resolve()):
                    raise ValueError("Đường dẫn file vượt thư mục khôi phục.")
                path.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                size = 0
                with archive.open(name) as source, path.open("wb") as output:
                    while chunk := source.read(1024 * 1024):
                        context.check()
                        digest.update(chunk)
                        size += len(chunk)
                        output.write(chunk)
                if size != expected["size"] or digest.hexdigest() != expected["sha256"]:
                    raise ValueError("Checksum file không khớp: " + name)
                if index % 20 == 0:
                    context.stage(f"Khôi phục file {index + 1}/{len(manifest['files'])}")
        # Sidecar JSON is consumed by the legacy renderer during subsequent edits.
        # Rebase its internal paths only after verifying the original archive checksums.
        changed = {}
        for path in destination.rglob("*.json"):
            if path.stat().st_size > 50_000_000:
                raise ValueError("JSON sidecar vượt giới hạn kích thước.")
            try:
                before = json.loads(path.read_text())
            except (ValueError, UnicodeError):
                continue
            after = rewrite(before, manifest["data_root"], str(destination))
            if after != before:
                blob = json.dumps(after, ensure_ascii=False, indent=2).encode()
                path.write_bytes(blob)
                changed[str(path.relative_to(destination))] = {
                    "sha256": hashlib.sha256(blob).hexdigest(),
                    "size_bytes": len(blob),
                }
        for row in records.get("artifacts", []):
            if row.get("path") in changed:
                row.update(changed[row["path"]])
        context.check()
        settings = context.mongo.settings.model_copy(
            update={"mongo_database": database, "data_dir": destination}
        )
        target = Mongo(settings)
        if database in target.client.list_database_names():
            raise ValueError("Tên database khôi phục đã tồn tại.")
        target.initialize()
        created = True
        for name, rows in records.items():
            if name == "schema_migrations":
                continue
            clean = rewrite(rows, manifest["data_root"], str(destination))
            if clean:
                target.db[name].insert_many(clean)
        context.publish(
            {},
            result={
                "database": database,
                "data_directory": str(destination),
                "message": (
                    "Đã khôi phục vào database mới. Dừng API/worker, đặt "
                    "MEETING_APP_MONGO_DATABASE và MEETING_APP_DATA_DIR theo kết quả rồi "
                    "khởi động lại. Phiên đăng nhập cũ không được khôi phục."
                ),
            },
        )
    except BaseException:
        if target and created:
            target.client.drop_database(database)
        shutil.rmtree(destination, ignore_errors=True)
        raise
    finally:
        if target:
            target.close()
