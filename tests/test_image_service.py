import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.models import Image, ImageStatus, ProjectAccess, ProjectRole, User
from app.services import image_service
from tests.helpers import FakeUploadFile, jpeg_bytes


def _pending_image(**overrides) -> Image:
    return Image(
        **{
            "project_id": 1,
            "uploaded_by_id": 1,
            "filename": "pic.jpg",
            "content_type": "image/jpeg",
            "status": ImageStatus.pending,
            "size_bytes": 1_000_000,
            "original_storage_key": "images/originals/1/1/pic.jpg",
            **overrides,
        }
    )


def _persist(db, image: Image) -> Image:
    db.add(image)
    db.commit()
    db.refresh(image)
    return image


# --- get_image_for_user ---------------------------------------------------


def test_get_image_for_user_raises_404_when_image_missing():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        image_service.get_image_for_user(db=db, image_id=1, user=User(id=1, login="alice"))

    assert exc_info.value.status_code == 404


def test_get_image_for_user_raises_404_when_no_project_access():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [
        Image(id=1, project_id=1, filename="pic.jpg"),
        None,
    ]

    with pytest.raises(HTTPException) as exc_info:
        image_service.get_image_for_user(db=db, image_id=1, user=User(id=1, login="alice"))

    assert exc_info.value.status_code == 404


def test_get_image_for_user_returns_image_when_access_granted():
    image = Image(id=1, project_id=1, filename="pic.jpg")
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [
        image,
        ProjectAccess(project_id=1, user_id=1, role=ProjectRole.owner),
    ]

    result = image_service.get_image_for_user(db=db, image_id=1, user=User(id=1, login="alice"))

    assert result is image


# --- read_image_content ---------------------------------------------------


def test_read_image_content_raises_409_when_not_ready():
    image = Image(id=1, project_id=1, filename="pic.jpg", status=ImageStatus.pending)

    with pytest.raises(HTTPException) as exc_info:
        image_service.read_image_content(image)

    assert exc_info.value.status_code == 409


def test_read_image_content_reads_from_storage_when_ready(monkeypatch):
    storage = MagicMock()
    storage.read.return_value = b"bytes"
    monkeypatch.setattr(image_service, "get_image_storage", lambda: storage)
    image = Image(id=1, project_id=1, filename="pic.jpg", status=ImageStatus.ready, storage_key="k")

    assert image_service.read_image_content(image) == b"bytes"
    storage.read.assert_called_once_with("k")


# --- create_image (upload -> pending, resize happens in the Lambda) --------


def test_create_image_uploads_original_and_creates_pending_image(db, monkeypatch):
    monkeypatch.setenv("MAX_USER_UPLOAD_BYTES_PER_PROJECT", str(10 * 1024 * 1024))
    storage = MagicMock()
    storage.save_original.return_value = "images/originals/1/1/pic.jpg"
    monkeypatch.setattr(image_service, "get_image_storage", lambda: storage)

    image = asyncio.run(
        image_service.create_image(db, 1, 1, FakeUploadFile("pic.jpg", jpeg_bytes()))
    )

    assert image.status == ImageStatus.pending
    assert image.storage_key is None
    assert image.original_storage_key == "images/originals/1/1/pic.jpg"


def test_create_image_raises_413_when_original_exceeds_quota(db, monkeypatch):
    monkeypatch.setenv("MAX_USER_UPLOAD_BYTES_PER_PROJECT", "10")
    storage = MagicMock()
    monkeypatch.setattr(image_service, "get_image_storage", lambda: storage)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(image_service.create_image(db, 1, 1, FakeUploadFile("pic.jpg", jpeg_bytes())))

    assert exc_info.value.status_code == 413
    assert db.query(Image).count() == 0
    storage.save_original.assert_not_called()


def test_create_image_raises_400_on_corrupt_image(db):
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(image_service.create_image(db, 1, 1, FakeUploadFile("pic.jpg", b"garbage")))

    assert exc_info.value.status_code == 400


def test_create_image_raises_400_on_unsupported_extension(db):
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(image_service.create_image(db, 1, 1, FakeUploadFile("pic.bmp", jpeg_bytes())))

    assert exc_info.value.status_code == 400


# --- finalize_image (Lambda callback) -------------------------------------


def test_finalize_image_promotes_to_ready_within_quota(db, monkeypatch):
    monkeypatch.setenv("MAX_USER_UPLOAD_BYTES_PER_PROJECT", str(10 * 1024 * 1024))
    storage = MagicMock()
    monkeypatch.setattr(image_service, "get_image_storage", lambda: storage)
    image = _persist(db, _pending_image())

    result = image_service.finalize_image(
        db, image.id, resized_size_bytes=200_000, width=256, height=256
    )

    assert result.status == ImageStatus.ready
    assert result.size_bytes == 200_000
    assert result.storage_key == "images/resized/1/1/pic.jpg"
    assert (result.width, result.height) == (256, 256)
    storage.delete.assert_called_once_with("images/originals/1/1/pic.jpg")


def test_finalize_image_accepts_resize_that_grew_but_still_fits(db, monkeypatch):
    """The reserved original size is released, so a modest growth is fine."""
    monkeypatch.setenv("MAX_USER_UPLOAD_BYTES_PER_PROJECT", str(10 * 1024 * 1024))
    monkeypatch.setattr(image_service, "get_image_storage", lambda: MagicMock())
    image = _persist(db, _pending_image(size_bytes=1_000_000))

    result = image_service.finalize_image(db, image.id, resized_size_bytes=1_200_000)

    assert result.status == ImageStatus.ready
    assert result.size_bytes == 1_200_000


def test_finalize_image_rejects_and_cleans_up_when_over_quota(db, monkeypatch):
    monkeypatch.setenv("MAX_USER_UPLOAD_BYTES_PER_PROJECT", "1024")
    storage = MagicMock()
    monkeypatch.setattr(image_service, "get_image_storage", lambda: storage)
    image = _persist(db, _pending_image(size_bytes=500))

    result = image_service.finalize_image(db, image.id, resized_size_bytes=2000)

    assert result.status == ImageStatus.rejected
    assert {call.args[0] for call in storage.delete.call_args_list} == {
        "images/originals/1/1/pic.jpg",
        "images/resized/1/1/pic.jpg",
    }


def test_finalize_image_rejects_when_lambda_reports_failure(db, monkeypatch):
    storage = MagicMock()
    monkeypatch.setattr(image_service, "get_image_storage", lambda: storage)
    image = _persist(db, _pending_image(size_bytes=500))

    result = image_service.finalize_image(db, image.id, failed=True)

    assert result.status == ImageStatus.rejected


def test_finalize_image_is_idempotent_for_already_resolved_image(db, monkeypatch):
    monkeypatch.setattr(image_service, "get_image_storage", lambda: MagicMock())
    image = _persist(
        db,
        _pending_image(
            status=ImageStatus.ready,
            size_bytes=100,
            storage_key="images/resized/1/1/pic.jpg",
        ),
    )

    result = image_service.finalize_image(db, image.id, resized_size_bytes=999)

    assert result.size_bytes == 100  # unchanged - no-op on a non-pending image


def test_finalize_image_raises_404_when_image_missing(db):
    with pytest.raises(HTTPException) as exc_info:
        image_service.finalize_image(db, 999, resized_size_bytes=100)

    assert exc_info.value.status_code == 404


def test_finalize_image_rejects_missing_size_when_not_failed(db, monkeypatch):
    """The schema guards this at the HTTP boundary, but finalize_image is callable
    directly - without the check it would crash on None arithmetic."""
    monkeypatch.setattr(image_service, "get_image_storage", lambda: MagicMock())
    image = _persist(db, _pending_image())

    with pytest.raises(HTTPException) as exc_info:
        image_service.finalize_image(db, image.id, resized_size_bytes=None, failed=False)

    assert exc_info.value.status_code == 400
    db.refresh(image)
    assert image.status == ImageStatus.pending  # left alone, not half-resolved
