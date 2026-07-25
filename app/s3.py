from pathlib import Path

from app.config import get_settings


def sanitize_filename(filename: str, fallback: str) -> str:
    return Path(filename).name.strip() or fallback


class S3ObjectStore:
    """Key-agnostic object operations against the app's bucket.

    Key layout is the caller's business - see app/storage.py for documents and
    app/image_storage.py for images. This class only moves bytes.
    """

    def __init__(self, bucket: str | None = None, client=None) -> None:
        settings = get_settings()
        self.bucket = bucket or settings.aws_s3_bucket
        self.client = client or self._build_client(settings)

    @staticmethod
    def _build_client(settings):
        import boto3

        return boto3.client("s3", region_name=settings.aws_region)

    def put(self, key: str, content: bytes) -> str:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=content)
        return key

    def read(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def delete_prefix(self, prefix: str) -> None:
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            keys = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
            if keys:
                self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": keys})
