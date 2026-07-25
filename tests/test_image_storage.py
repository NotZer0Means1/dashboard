from unittest.mock import MagicMock

from app.image_storage import (
    S3ImageStorage,
    build_original_key,
    build_resized_key,
    get_image_storage,
)


def test_build_original_and_resized_keys_use_distinct_prefixes():
    # The prefixes must differ, or the Lambda's own write re-triggers the S3 event.
    assert build_original_key(1, 7, "photo.jpg") == "images/originals/1/7/photo.jpg"
    assert build_resized_key(1, 7, "photo.jpg") == "images/resized/1/7/photo.jpg"


def test_build_key_sanitizes_path_traversal_in_filename():
    assert build_original_key(1, 7, "../../etc/passwd") == "images/originals/1/7/passwd"


def test_save_original_puts_object_at_originals_key():
    client = MagicMock()
    storage = S3ImageStorage(bucket="test-bucket", client=client)

    key = storage.save_original(project_id=1, image_id=7, filename="photo.jpg", content=b"orig")

    assert key == "images/originals/1/7/photo.jpg"
    client.put_object.assert_called_once_with(Bucket="test-bucket", Key=key, Body=b"orig")


def test_read_returns_object_body():
    client = MagicMock()
    client.get_object.return_value = {"Body": MagicMock(read=lambda: b"small")}
    storage = S3ImageStorage(bucket="test-bucket", client=client)

    assert storage.read("images/resized/1/7/photo.jpg") == b"small"


def test_delete_removes_object():
    client = MagicMock()
    storage = S3ImageStorage(bucket="test-bucket", client=client)

    storage.delete("images/originals/1/7/photo.jpg")

    client.delete_object.assert_called_once_with(
        Bucket="test-bucket", Key="images/originals/1/7/photo.jpg"
    )


def test_delete_project_images_sweeps_both_prefixes():
    client = MagicMock()
    pages = {
        "images/originals/1/": [{"Contents": [{"Key": "images/originals/1/7/photo.jpg"}]}],
        "images/resized/1/": [{"Contents": [{"Key": "images/resized/1/7/photo.jpg"}]}],
    }
    client.get_paginator.return_value.paginate.side_effect = lambda Bucket, Prefix: pages[Prefix]
    storage = S3ImageStorage(bucket="test-bucket", client=client)

    storage.delete_project_images(1)

    deleted = {
        delete_call.kwargs["Delete"]["Objects"][0]["Key"]
        for delete_call in client.delete_objects.call_args_list
    }
    assert deleted == {"images/originals/1/7/photo.jpg", "images/resized/1/7/photo.jpg"}


def test_get_image_storage_is_cached():
    assert get_image_storage() is get_image_storage()
