from functools import lru_cache

from app.s3 import S3ObjectStore, project_prefix, sanitize_filename


def _build_key(project_id: int, document_id: int, filename: str) -> str:
    # projects/{project_id}/documents/{document_id}/{filename} - the sibling of
    # the images subtree, so a project is one folder in the bucket.
    safe = sanitize_filename(filename, "document")
    return f"{project_prefix(project_id)}/documents/{document_id}/{safe}"


class S3DocumentStorage(S3ObjectStore):
    """Document key layout on top of the shared object store."""

    def save(self, project_id: int, document_id: int, filename: str, content: bytes) -> str:
        return self.put(_build_key(project_id, document_id, filename), content)

    def overwrite(self, storage_key: str, content: bytes) -> None:
        self.put(storage_key, content)

    def delete_project_dir(self, project_id: int) -> None:
        self.delete_prefix(f"{project_prefix(project_id)}/documents/")


@lru_cache
def get_storage() -> S3DocumentStorage:
    # Cached: building a boto3 client costs ~6ms and is not thread-safe to do
    # concurrently, and this is called on every storage-touching request.
    return S3DocumentStorage()
