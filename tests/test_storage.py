from unittest.mock import MagicMock

import pytest

from app.storage import S3DocumentStorage, get_storage


def test_save_builds_key_and_puts_object():
    client = MagicMock()
    storage = S3DocumentStorage(bucket="test-bucket", client=client)

    key = storage.save(project_id=1, document_id=7, filename="report.pdf", content=b"hello")

    assert key == "projects/1/documents/7/report.pdf"
    client.put_object.assert_called_once_with(Bucket="test-bucket", Key=key, Body=b"hello")


def test_save_sanitizes_path_traversal_in_filename():
    client = MagicMock()
    storage = S3DocumentStorage(bucket="test-bucket", client=client)

    key = storage.save(
        project_id=1, document_id=7, filename="../../etc/passwd", content=b"malicious"
    )

    assert key == "projects/1/documents/7/passwd"


def test_overwrite_puts_object_at_existing_key():
    client = MagicMock()
    storage = S3DocumentStorage(bucket="test-bucket", client=client)

    storage.overwrite("projects/1/documents/7/report.pdf", b"v2")

    client.put_object.assert_called_once_with(
        Bucket="test-bucket", Key="projects/1/documents/7/report.pdf", Body=b"v2"
    )


def test_read_returns_object_body():
    client = MagicMock()
    client.get_object.return_value = {"Body": MagicMock(read=lambda: b"hello")}
    storage = S3DocumentStorage(bucket="test-bucket", client=client)

    assert storage.read("projects/1/documents/7/report.pdf") == b"hello"


def test_read_closes_the_streaming_body():
    # botocore holds the connection out of the pool until the body is closed,
    # so a leak here starves the pool under load. Regression guard for PR #5.
    client = MagicMock()
    body = MagicMock(read=lambda: b"hello")
    client.get_object.return_value = {"Body": body}
    storage = S3DocumentStorage(bucket="test-bucket", client=client)

    storage.read("projects/1/documents/7/report.pdf")

    body.close.assert_called_once()


def test_read_closes_the_streaming_body_even_when_read_fails():
    client = MagicMock()
    body = MagicMock()
    body.read.side_effect = OSError("connection reset")
    client.get_object.return_value = {"Body": body}
    storage = S3DocumentStorage(bucket="test-bucket", client=client)

    with pytest.raises(OSError):
        storage.read("projects/1/documents/7/report.pdf")

    body.close.assert_called_once()


def test_delete_removes_object():
    client = MagicMock()
    storage = S3DocumentStorage(bucket="test-bucket", client=client)

    storage.delete("projects/1/documents/7/report.pdf")

    client.delete_object.assert_called_once_with(
        Bucket="test-bucket", Key="projects/1/documents/7/report.pdf"
    )


def test_delete_project_dir_deletes_all_objects_under_prefix():
    client = MagicMock()
    objects = [
        {"Key": "projects/1/documents/7/a.pdf"},
        {"Key": "projects/1/documents/8/b.docx"},
    ]
    client.get_paginator.return_value.paginate.return_value = [{"Contents": objects}]
    storage = S3DocumentStorage(bucket="test-bucket", client=client)

    storage.delete_project_dir(1)

    client.get_paginator.return_value.paginate.assert_called_once_with(
        Bucket="test-bucket", Prefix="projects/1/documents/"
    )
    client.delete_objects.assert_called_once_with(Bucket="test-bucket", Delete={"Objects": objects})


def test_delete_project_dir_skips_delete_call_when_prefix_is_empty():
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [{"Contents": []}]
    storage = S3DocumentStorage(bucket="test-bucket", client=client)

    storage.delete_project_dir(1)

    client.delete_objects.assert_not_called()


def test_get_storage_is_cached():
    # Rebuilding the boto3 client per call is the thing the cache exists to avoid.
    assert get_storage() is get_storage()
