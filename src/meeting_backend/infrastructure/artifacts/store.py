"""Private local artifact storage; IDs never expose arbitrary filesystem paths."""

import hashlib
import mimetypes
from pathlib import Path

from meeting_backend.core.errors import AppError
from meeting_backend.infrastructure.mongodb.client import new_id, now, public

AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".webm", ".mp4"}
DOCUMENT_EXTENSIONS = {".doc", ".docx", ".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}


class ArtifactStore:
    def __init__(self, mongo):
        self.mongo = mongo
        self.root = mongo.settings.data_dir.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, artifact):
        path = (self.root / artifact["path"]).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            raise AppError("ARTIFACT_MISSING", "File không còn tồn tại.", 404)
        return path

    def register(
        self, path: Path, owner_id: str, *, name=None, visibility="private", resource_id=None
    ):
        path = path.resolve()
        if not path.is_relative_to(self.root):
            raise AppError("INVALID_ARTIFACT", "File nằm ngoài kho dữ liệu ứng dụng.")
        relative = str(path.relative_to(self.root))
        prior = self.mongo.db.artifacts.find_one({"path": relative})
        if prior:
            return prior
        h = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                h.update(chunk)
        artifact = {
            "_id": new_id(),
            "owner_id": owner_id,
            "path": relative,
            "name": name or path.name,
            "visibility": visibility,
            "resource_id": resource_id,
            "sha256": h.hexdigest(),
            "size_bytes": path.stat().st_size,
            "media_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            "created_at": now(),
        }
        self.mongo.db.artifacts.insert_one(artifact)
        return artifact

    def upload(self, file, owner_id: str, allowed, *, resource_id=None, visibility="private"):
        name = Path(file.filename or "file").name
        suffix = Path(name).suffix.lower()
        if suffix not in allowed:
            raise AppError("UNSUPPORTED_FILE", "Định dạng file chưa được hỗ trợ.", 422)
        directory = self.root / "uploads" / owner_id / new_id()
        directory.mkdir(parents=True)
        path = directory / ("original" + suffix)
        size = 0
        try:
            with path.open("wb") as stream:
                while chunk := file.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > self.mongo.settings.max_upload_bytes:
                        raise AppError("FILE_TOO_LARGE", "File vượt giới hạn dung lượng.", 413)
                    stream.write(chunk)
            if not size:
                raise AppError("EMPTY_FILE", "File rỗng.", 422)
            return self.register(
                path, owner_id, name=name, resource_id=resource_id, visibility=visibility
            )
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    def view(self, artifact):
        return {**public(artifact), "url": f"/api/v1/artifacts/{artifact['_id']}"}
