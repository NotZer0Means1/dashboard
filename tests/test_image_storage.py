from unittest.mock import MagicMock

from app.image_storage import (
    S3ImageStorage,
    build_original_key,
    build_resized_key,
    get_image_storage,
)


def test_both_copies_live_in_the_image_s_own_folder():
    # Same folder, distinguished only by the last segment - that segment is what
    # the resize Lambda checks to avoid re-triggering on its own write.
    assert build_original_key(1, 7, "photo.jpg") == "projects/1/images/7/original/photo.jpg"
    assert build_resized_key(1, 7, "photo.jpg") == "projects/1/images/7/resized/photo.jpg"


def test_build_key_sanitizes_path_traversal_in_filename():
    assert build_original_key(1, 7, "../../etc/passwd") == "projects/1/images/7/original/passwd"


def test_save_original_puts_object_at_originals_key():
    client = MagicMock()
    storage = S3ImageStorage(bucket="test-bucket", client=client)

    key = storage.save_original(project_id=1, image_id=7, filename="photo.jpg", content=b"orig")

    assert key == "projects/1/images/7/original/photo.jpg"
    client.put_object.assert_called_once_with(Bucket="test-bucket", Key=key, Body=b"orig")


def test_read_returns_object_body():
    client = MagicMock()
    client.get_object.return_value = {"Body": MagicMock(read=lambda: b"small")}
    storage = S3ImageStorage(bucket="test-bucket", client=client)

    assert storage.read("projects/1/images/7/resized/photo.jpg") == b"small"


def test_delete_removes_object():
    client = MagicMock()
    storage = S3ImageStorage(bucket="test-bucket", client=client)

    storage.delete("projects/1/images/7/original/photo.jpg")

    client.delete_object.assert_called_once_with(
        Bucket="test-bucket", Key="projects/1/images/7/original/photo.jpg"
    )


def test_delete_project_images_takes_both_copies_in_one_sweep():
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [
        {
            "Contents": [
                {"Key": "projects/1/images/7/original/photo.jpg"},
                {"Key": "projects/1/images/7/resized/photo.jpg"},
            ]
        }
    ]
    storage = S3ImageStorage(bucket="test-bucket", client=client)

    storage.delete_project_images(1)

    client.get_paginator.return_value.paginate.assert_called_once_with(
        Bucket="test-bucket", Prefix="projects/1/images/"
    )
    deleted = {
        key["Key"]
        for call in client.delete_objects.call_args_list
        for key in call.kwargs["Delete"]["Objects"]
    }
    assert deleted == {
        "projects/1/images/7/original/photo.jpg",
        "projects/1/images/7/resized/photo.jpg",
    }


def test_delete_project_images_does_not_touch_documents():
    """The sweep is scoped to the images subtree, not the whole project folder -
    deleting a project's images must leave its documents alone."""
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [{"Contents": []}]
    storage = S3ImageStorage(bucket="test-bucket", client=client)

    storage.delete_project_images(1)

    prefix = client.get_paginator.return_value.paginate.call_args.kwargs["Prefix"]
    assert prefix == "projects/1/images/"


def test_get_image_storage_is_cached():
    assert get_image_storage() is get_image_storage()
