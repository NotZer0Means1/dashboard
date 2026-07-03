import shutil
import uuid
from pathlib import Path

from app.config import get_settings


class LocalDocumentStorage:
    """Filesystem-backed document storage for the MVP.

    Kept behind a narrow save/read/overwrite/delete interface so it can be
    swapped for an S3-backed implementation later without touching callers.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or get_settings().storage_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, storage_key: str) -> Path:
        return self.base_dir / storage_key

    def save(self, project_id: int, filename: str, content: bytes) -> str:
        suffix = Path(filename).suffix
        storage_key = f"{project_id}/{uuid.uuid4().hex}{suffix}"
        path = self._path(storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return storage_key

    def overwrite(self, storage_key: str, content: bytes) -> None:
        self._path(storage_key).write_bytes(content)

    def read(self, storage_key: str) -> bytes:
        return self._path(storage_key).read_bytes()

    def delete(self, storage_key: str) -> None:
        self._path(storage_key).unlink(missing_ok=True)

    def delete_project_dir(self, project_id: int) -> None:
        shutil.rmtree(self.base_dir / str(project_id), ignore_errors=True)


def get_storage() -> LocalDocumentStorage:
    return LocalDocumentStorage()
