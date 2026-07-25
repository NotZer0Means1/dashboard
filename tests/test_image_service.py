import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.lambda_client import ResizeInvocationError, ResizeResult
from app.models import Image, ImageStatus, ProjectAccess, ProjectRole, User
from app.services import image_service
from tests.helpers import FakeUploadFile, jpeg_bytes


def _stored_image(**overrides) -> Image:
    return Image(
        **{
            "project_id": 1,
            "uploaded_by_id": 1,
            "filename": "pic.jpg",
            "content_type": "image/jpeg",
            "status": ImageStatus.stored,
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


def _mock_lambda(monkeypatch, result) -> MagicMock:
    client = MagicMock()
    if isinstance(result, Exception):
        client.resize.side_effect = result
    else:
        client.resize.return_value = result
    monkeypatch.setattr(image_service, "get_resize_lambda_client", lambda: client)
    return client


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


def test_read_image_content_serves_the_original_when_never_resized(monkeypatch):
    """An unresized image is a normal downloadable image, not an error case."""
    storage = MagicMock()
    storage.read.return_value = b"original-bytes"
    monkeypatch.setattr(image_service, "get_image_storage", lambda: storage)
    image = _stored_image(id=1, storage_key=None)

    assert image_service.read_image_content(image) == b"original-bytes"
    storage.read.assert_called_once_with("images/originals/1/1/pic.jpg")


def test_read_image_content_prefers_the_resized_copy_once_it_exists(monkeypatch):
    storage = MagicMock()
    storage.read.return_value = b"resized-bytes"
    monkeypatch.setattr(image_service, "get_image_storage", lambda: storage)
    image = _stored_image(id=1, status=ImageStatus.ready, storage_key="images/resized/1/1/pic.jpg")

    assert image_service.read_image_content(image) == b"resized-bytes"
    storage.read.assert_called_once_with("images/resized/1/1/pic.jpg")


def test_read_image_content_raises_409_when_rejected():
    image = _stored_image(id=1, status=ImageStatus.rejected)

    with pytest.raises(HTTPException) as exc_info:
        image_service.read_image_content(image)

    assert exc_info.value.status_code == 409


# --- create_image (upload only - no Lambda runs) --------------------------


def test_create_image_uploads_original_and_creates_stored_image(db, monkeypatch):
    monkeypatch.setenv("MAX_USER_UPLOAD_BYTES_PER_PROJECT", str(10 * 1024 * 1024))
    storage = MagicMock()
    storage.save_original.return_value = "images/originals/1/1/pic.jpg"
    monkeypatch.setattr(image_service, "get_image_storage", lambda: storage)

    image = asyncio.run(
        image_service.create_image(db, 1, 1, FakeUploadFile("pic.jpg", jpeg_bytes()))
    )

    assert image.status == ImageStatus.stored
    assert image.storage_key is None
    assert image.resized_size_bytes is None
    assert image.original_storage_key == "images/originals/1/1/pic.jpg"


def test_create_image_does_not_invoke_the_resize_lambda(db, monkeypatch):
    """Uploading must not cost an invocation - resizing is user-triggered now."""
    monkeypatch.setenv("MAX_USER_UPLOAD_BYTES_PER_PROJECT", str(10 * 1024 * 1024))
    storage = MagicMock()
    storage.save_original.return_value = "images/originals/1/1/pic.jpg"
    monkeypatch.setattr(image_service, "get_image_storage", lambda: storage)
    client = _mock_lambda(monkeypatch, ResizeResult(ok=True))

    asyncio.run(image_service.create_image(db, 1, 1, FakeUploadFile("pic.jpg", jpeg_bytes())))

    client.resize.assert_not_called()


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


# --- resize_image (synchronous Lambda invoke) -----------------------------


def test_resize_image_promotes_to_ready_and_keeps_the_original(db, monkeypatch):
    monkeypatch.setenv("MAX_USER_UPLOAD_BYTES_PER_PROJECT", str(10 * 1024 * 1024))
    storage = MagicMock()
    monkeypatch.setattr(image_service, "get_image_storage", lambda: storage)
    _mock_lambda(
        monkeypatch,
        ResizeResult(ok=True, resized_size_bytes=200_000, width=512, height=384),
    )
    image = _persist(db, _stored_image())

    result = image_service.resize_image(db, image, width=512, height=512)

    assert result.status == ImageStatus.ready
    assert result.size_bytes == 1_000_000  # original untouched
    assert result.resized_size_bytes == 200_000
    assert result.storage_key == "images/resized/1/1/pic.jpg"
    assert (result.width, result.height) == (512, 384)
    storage.delete.assert_not_called()


def test_resize_image_passes_requested_dimensions_to_the_lambda(db, monkeypatch):
    monkeypatch.setenv("MAX_USER_UPLOAD_BYTES_PER_PROJECT", str(10 * 1024 * 1024))
    storage = MagicMock()
    storage.bucket = "test-bucket"
    monkeypatch.setattr(image_service, "get_image_storage", lambda: storage)
    client = _mock_lambda(
        monkeypatch, ResizeResult(ok=True, resized_size_bytes=1000, width=256, height=256)
    )
    image = _persist(db, _stored_image())

    image_service.resize_image(db, image, width=256, height=128)

    assert client.resize.call_args.kwargs == {
        "bucket": "test-bucket",
        "source_key": "images/originals/1/1/pic.jpg",
        "target_key": "images/resized/1/1/pic.jpg",
        "filename": "pic.jpg",
        "width": 256,
        "height": 128,
    }


def test_resize_image_can_be_rerun_and_only_charges_the_difference(db, monkeypatch):
    """Re-resizing works off the retained original, so it must not double-charge."""
    monkeypatch.setenv("MAX_USER_UPLOAD_BYTES_PER_PROJECT", str(10 * 1024 * 1024))
    monkeypatch.setattr(image_service, "get_image_storage", lambda: MagicMock())
    _mock_lambda(
        monkeypatch, ResizeResult(ok=True, resized_size_bytes=300_000, width=800, height=800)
    )
    image = _persist(
        db,
        _stored_image(
            status=ImageStatus.ready,
            resized_size_bytes=200_000,
            storage_key="images/resized/1/1/pic.jpg",
        ),
    )

    result = image_service.resize_image(db, image, width=800, height=800)

    assert result.resized_size_bytes == 300_000
    # 1_000_000 original + 300_000 resized, not 1_000_000 + 200_000 + 300_000
    from app.services import quota_service

    assert quota_service.project_bytes_used(db, 1, 1) == 1_300_000


def test_resize_image_raises_413_and_reverts_when_resized_copy_overflows_quota(db, monkeypatch):
    monkeypatch.setenv("MAX_USER_UPLOAD_BYTES_PER_PROJECT", "1024")
    storage = MagicMock()
    monkeypatch.setattr(image_service, "get_image_storage", lambda: storage)
    _mock_lambda(monkeypatch, ResizeResult(ok=True, resized_size_bytes=2000, width=512, height=512))
    image = _persist(db, _stored_image(size_bytes=500))

    with pytest.raises(HTTPException) as exc_info:
        image_service.resize_image(db, image, width=512, height=512)

    assert exc_info.value.status_code == 413
    db.refresh(image)
    # Reverted to a state that matches storage, with the original still intact.
    assert image.status == ImageStatus.stored
    assert image.resized_size_bytes is None
    assert image.storage_key is None
    storage.delete.assert_called_once_with("images/resized/1/1/pic.jpg")


def test_resize_image_rejects_when_lambda_cannot_decode(db, monkeypatch):
    monkeypatch.setattr(image_service, "get_image_storage", lambda: MagicMock())
    _mock_lambda(monkeypatch, ResizeResult(ok=False, error="cannot identify image file"))
    image = _persist(db, _stored_image())

    with pytest.raises(HTTPException) as exc_info:
        image_service.resize_image(db, image, width=512, height=512)

    assert exc_info.value.status_code == 422
    db.refresh(image)
    assert image.status == ImageStatus.rejected


def test_resize_image_raises_502_when_the_lambda_cannot_be_invoked(db, monkeypatch):
    monkeypatch.setattr(image_service, "get_image_storage", lambda: MagicMock())
    _mock_lambda(monkeypatch, ResizeInvocationError("function not found"))
    image = _persist(db, _stored_image())

    with pytest.raises(HTTPException) as exc_info:
        image_service.resize_image(db, image, width=512, height=512)

    assert exc_info.value.status_code == 502
    db.refresh(image)
    assert image.status == ImageStatus.stored  # left alone, still resizable


def test_resize_image_raises_409_when_there_is_no_stored_original(db, monkeypatch):
    monkeypatch.setattr(image_service, "get_image_storage", lambda: MagicMock())
    image = _persist(db, _stored_image(original_storage_key=""))

    with pytest.raises(HTTPException) as exc_info:
        image_service.resize_image(db, image, width=512, height=512)

    assert exc_info.value.status_code == 409


# --- finalize_image (manual out-of-band override) -------------------------


def test_finalize_image_records_an_externally_performed_resize(db, monkeypatch):
    monkeypatch.setenv("MAX_USER_UPLOAD_BYTES_PER_PROJECT", str(10 * 1024 * 1024))
    monkeypatch.setattr(image_service, "get_image_storage", lambda: MagicMock())
    image = _persist(db, _stored_image())

    result = image_service.finalize_image(
        db, image.id, resized_size_bytes=200_000, width=256, height=256
    )

    assert result.status == ImageStatus.ready
    assert result.resized_size_bytes == 200_000
    assert result.storage_key == "images/resized/1/1/pic.jpg"


def test_finalize_image_rejects_when_caller_reports_failure(db, monkeypatch):
    monkeypatch.setattr(image_service, "get_image_storage", lambda: MagicMock())
    image = _persist(db, _stored_image(size_bytes=500))

    result = image_service.finalize_image(db, image.id, failed=True)

    assert result.status == ImageStatus.rejected


def test_finalize_image_raises_404_when_image_missing(db):
    with pytest.raises(HTTPException) as exc_info:
        image_service.finalize_image(db, 999, resized_size_bytes=100)

    assert exc_info.value.status_code == 404


def test_finalize_image_rejects_missing_size_when_not_failed(db, monkeypatch):
    """The schema guards this at the HTTP boundary, but finalize_image is callable
    directly - without the check it would crash on None arithmetic."""
    monkeypatch.setattr(image_service, "get_image_storage", lambda: MagicMock())
    image = _persist(db, _stored_image())

    with pytest.raises(HTTPException) as exc_info:
        image_service.finalize_image(db, image.id, resized_size_bytes=None, failed=False)

    assert exc_info.value.status_code == 400
    db.refresh(image)
    assert image.status == ImageStatus.stored  # left alone, not half-resolved
