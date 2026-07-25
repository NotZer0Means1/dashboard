import pytest
from fastapi import HTTPException

from app.models import Document, Image, ImageStatus
from app.services import quota_service


def _document(**overrides) -> Document:
    return Document(
        **{
            "project_id": 1,
            "uploaded_by_id": 1,
            "filename": "a.pdf",
            "content_type": "application/pdf",
            "size_bytes": 1_000_000,
            "storage_key": "1/1/a.pdf",
            **overrides,
        }
    )


def _image(**overrides) -> Image:
    return Image(
        **{
            "project_id": 1,
            "uploaded_by_id": 1,
            "filename": "b.jpg",
            "content_type": "image/jpeg",
            "status": ImageStatus.ready,
            "size_bytes": 500_000,
            "original_storage_key": "images/originals/1/1/b.jpg",
            "storage_key": "images/resized/1/1/b.jpg",
            **overrides,
        }
    )


def test_project_bytes_used_sums_documents_and_images(db):
    db.add_all([_document(), _image()])
    db.commit()

    assert quota_service.project_bytes_used(db, project_id=1, user_id=1) == 1_500_000


def test_project_bytes_used_counts_stored_images_but_not_rejected(db):
    db.add_all(
        [
            _image(status=ImageStatus.stored, size_bytes=200_000, storage_key=None),
            _image(status=ImageStatus.rejected, size_bytes=9_000_000),
        ]
    )
    db.commit()

    assert quota_service.project_bytes_used(db, project_id=1, user_id=1) == 200_000


def test_project_bytes_used_counts_both_original_and_resized_copies(db):
    """The original is kept as the resize source, so a resized image occupies both."""
    db.add_all([_image(size_bytes=500_000, resized_size_bytes=120_000)])
    db.commit()

    assert quota_service.project_bytes_used(db, project_id=1, user_id=1) == 620_000


def test_project_bytes_used_only_counts_matching_project_and_user(db):
    db.add_all([_document(project_id=2), _image(uploaded_by_id=2)])
    db.commit()

    assert quota_service.project_bytes_used(db, project_id=1, user_id=1) == 0


def test_has_room_is_true_when_addition_fits(db, monkeypatch):
    monkeypatch.setenv("MAX_USER_UPLOAD_BYTES_PER_PROJECT", str(10 * 1024 * 1024))
    db.add(_document(size_bytes=8 * 1024 * 1024))
    db.commit()

    assert quota_service.has_room(db, 1, 1, 1 * 1024 * 1024) is True


def test_has_room_is_false_when_addition_overflows(db, monkeypatch):
    monkeypatch.setenv("MAX_USER_UPLOAD_BYTES_PER_PROJECT", str(10 * 1024 * 1024))
    db.add(_document(size_bytes=8 * 1024 * 1024))
    db.commit()

    assert quota_service.has_room(db, 1, 1, 3 * 1024 * 1024) is False


def test_has_room_allows_negative_delta_that_frees_space(db, monkeypatch):
    """Replacing a big file with a smaller one must pass even when already at the cap."""
    monkeypatch.setenv("MAX_USER_UPLOAD_BYTES_PER_PROJECT", str(10 * 1024 * 1024))
    db.add(_document(size_bytes=10 * 1024 * 1024))
    db.commit()

    assert quota_service.has_room(db, 1, 1, -5 * 1024 * 1024) is True


def test_enforce_quota_raises_413_when_over_limit(db, monkeypatch):
    monkeypatch.setenv("MAX_USER_UPLOAD_BYTES_PER_PROJECT", str(1024))
    db.add(_document(size_bytes=1000))
    db.commit()

    with pytest.raises(HTTPException) as exc_info:
        quota_service.enforce_quota(db, project_id=1, user_id=1, additional_bytes=100)

    assert exc_info.value.status_code == 413


def test_enforce_quota_allows_within_limit(db, monkeypatch):
    monkeypatch.setenv("MAX_USER_UPLOAD_BYTES_PER_PROJECT", str(10 * 1024 * 1024))
    db.add(_document(size_bytes=8 * 1024 * 1024))
    db.commit()

    quota_service.enforce_quota(db, project_id=1, user_id=1, additional_bytes=1 * 1024 * 1024)
