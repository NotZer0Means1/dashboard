import shutil
from pathlib import Path
from typing import Protocol

from app.config import get_settings


def _sanitize_filename(filename: str) -> str:
    return Path(filename).name.strip() or "document"


def _build_key(project_id: int, document_id: int, filename: str) -> str:
    return f"{project_id}/{document_id}/{_sanitize_filename(filename)}"


class DocumentStorage(Protocol):
    def save(self, project_id: int, document_id: int, filename: str, content: bytes) -> str: ...

    def overwrite(self, storage_key: str, content: bytes) -> None: ...

    def read(self, storage_key: str) -> bytes: ...

    def delete(self, storage_key: str) -> None: ...

    def delete_project_dir(self, project_id: int) -> None: ...


class LocalDocumentStorage:
    """Filesystem-backed document storage for local development."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or get_settings().storage_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, storage_key: str) -> Path:
        return self.base_dir / storage_key

    def save(self, project_id: int, document_id: int, filename: str, content: bytes) -> str:
        storage_key = _build_key(project_id, document_id, filename)
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


class S3DocumentStorage:
    """S3-backed document storage, backed by real AWS."""

    def __init__(self, bucket: str | None = None, client=None) -> None:
        settings = get_settings()
        self.bucket = bucket or settings.aws_s3_bucket
        self.client = client or self._build_client(settings)

    @staticmethod
    def _build_client(settings):
        import boto3

        return boto3.client("s3", region_name=settings.aws_region)

    def save(self, project_id: int, document_id: int, filename: str, content: bytes) -> str:
        storage_key = _build_key(project_id, document_id, filename)
        self.client.put_object(Bucket=self.bucket, Key=storage_key, Body=content)
        return storage_key

    def overwrite(self, storage_key: str, content: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=storage_key, Body=content)

    def read(self, storage_key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=storage_key)
        body = response["Body"]
        try:
            return body.read()
        finally:
            body.close()

    def delete(self, storage_key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=storage_key)

    def delete_project_dir(self, project_id: int) -> None:
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=f"{project_id}/"):
            keys = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
            if keys:
                self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": keys})


def get_storage() -> DocumentStorage:
    if get_settings().storage_backend == "s3":
        return S3DocumentStorage()
    return LocalDocumentStorage()
