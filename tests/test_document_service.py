import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.database import Base
from app.models import Document, ProjectAccess, ProjectRole, User
from app.services import document_service


class FakeUploadFile:
    def __init__(self, filename: str, content: bytes, content_type: str = "application/pdf"):
        self.filename = filename
        self.content_type = content_type
        self._content = content

    async def read(self) -> bytes:
        return self._content


def test_get_document_for_user_raises_404_when_document_missing():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    user = User(id=1, login="alice")

    with pytest.raises(HTTPException) as exc_info:
        document_service.get_document_for_user(db=db, document_id=1, user=user)

    assert exc_info.value.status_code == 404


def test_get_document_for_user_raises_404_when_no_project_access():
    document = Document(id=1, project_id=1, filename="report.pdf")
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [document, None]
    user = User(id=1, login="alice")

    with pytest.raises(HTTPException) as exc_info:
        document_service.get_document_for_user(db=db, document_id=1, user=user)

    assert exc_info.value.status_code == 404


def test_get_document_for_user_returns_document_when_access_granted():
    document = Document(id=1, project_id=1, filename="report.pdf")
    access = ProjectAccess(project_id=1, user_id=1, role=ProjectRole.owner)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [document, access]
    user = User(id=1, login="alice")

    result = document_service.get_document_for_user(db=db, document_id=1, user=user)

    assert result is document


def test_user_project_storage_used_returns_zero_when_no_documents():
    db = MagicMock()
    db.query.return_value.filter.return_value.scalar.return_value = None

    assert document_service._user_project_storage_used(db, project_id=1, user_id=1) == 0


def test_user_project_storage_used_only_counts_matching_user_and_project():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        # Same user, other project; same project, other user; and the one that should count.
        db.add_all(
            [
                Document(
                    project_id=1,
                    uploaded_by_id=1,
                    filename="a.pdf",
                    content_type="application/pdf",
                    size_bytes=1_000_000,
                    storage_key="1/1/a.pdf",
                ),
                Document(
                    project_id=2,
                    uploaded_by_id=1,
                    filename="b.pdf",
                    content_type="application/pdf",
                    size_bytes=2_000_000,
                    storage_key="2/2/b.pdf",
                ),
                Document(
                    project_id=1,
                    uploaded_by_id=2,
                    filename="c.pdf",
                    content_type="application/pdf",
                    size_bytes=4_000_000,
                    storage_key="1/3/c.pdf",
                ),
            ]
        )
        db.commit()

        assert document_service._user_project_storage_used(db, project_id=1, user_id=1) == 1_000_000
    finally:
        db.close()
        engine.dispose()


def test_enforce_upload_quota_allows_when_within_limit(monkeypatch):
    monkeypatch.setenv("MAX_USER_UPLOAD_BYTES_PER_PROJECT", str(10 * 1024 * 1024))
    get_settings.cache_clear()
    db = MagicMock()
    db.query.return_value.filter.return_value.scalar.return_value = 8 * 1024 * 1024

    document_service._enforce_upload_quota(
        db, project_id=1, user_id=1, additional_bytes=1 * 1024 * 1024
    )

    get_settings.cache_clear()


def test_enforce_upload_quota_raises_when_exceeding_limit(monkeypatch):
    monkeypatch.setenv("MAX_USER_UPLOAD_BYTES_PER_PROJECT", str(10 * 1024 * 1024))
    get_settings.cache_clear()
    db = MagicMock()
    db.query.return_value.filter.return_value.scalar.return_value = 8 * 1024 * 1024

    with pytest.raises(HTTPException) as exc_info:
        document_service._enforce_upload_quota(
            db, project_id=1, user_id=1, additional_bytes=3 * 1024 * 1024
        )

    assert exc_info.value.status_code == 413
    get_settings.cache_clear()


def test_create_documents_raises_413_when_exceeding_quota(monkeypatch):
    monkeypatch.setenv("MAX_USER_UPLOAD_BYTES_PER_PROJECT", str(10 * 1024 * 1024))
    get_settings.cache_clear()
    db = MagicMock()
    db.query.return_value.filter.return_value.scalar.return_value = 8 * 1024 * 1024
    file = FakeUploadFile("report.pdf", content=b"x" * (3 * 1024 * 1024))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            document_service.create_documents(db, project_id=1, uploader_id=1, files=[file])
        )

    assert exc_info.value.status_code == 413
    db.add.assert_not_called()
    get_settings.cache_clear()


def test_create_documents_succeeds_when_within_quota(monkeypatch):
    monkeypatch.setenv("MAX_USER_UPLOAD_BYTES_PER_PROJECT", str(10 * 1024 * 1024))
    get_settings.cache_clear()
    db = MagicMock()
    db.query.return_value.filter.return_value.scalar.return_value = 8 * 1024 * 1024
    storage = MagicMock()
    storage.save.return_value = "1/1/report.pdf"
    monkeypatch.setattr(document_service, "get_storage", lambda: storage)
    file = FakeUploadFile("report.pdf", content=b"x" * (1024 * 1024))

    created = asyncio.run(
        document_service.create_documents(db, project_id=1, uploader_id=1, files=[file])
    )

    assert len(created) == 1
    db.commit.assert_called_once()
    get_settings.cache_clear()


def test_update_document_raises_413_when_replacement_exceeds_quota(monkeypatch):
    monkeypatch.setenv("MAX_USER_UPLOAD_BYTES_PER_PROJECT", str(10 * 1024 * 1024))
    get_settings.cache_clear()
    document = Document(
        id=1, project_id=1, filename="report.pdf", size_bytes=1 * 1024 * 1024, uploaded_by_id=1
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.scalar.return_value = 8 * 1024 * 1024
    file = FakeUploadFile("report.pdf", content=b"x" * (4 * 1024 * 1024))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(document_service.update_document(db, document, file))

    assert exc_info.value.status_code == 413
    get_settings.cache_clear()


def test_update_document_allows_replacement_within_quota(monkeypatch):
    monkeypatch.setenv("MAX_USER_UPLOAD_BYTES_PER_PROJECT", str(10 * 1024 * 1024))
    get_settings.cache_clear()
    document = Document(
        id=1, project_id=1, filename="report.pdf", size_bytes=1 * 1024 * 1024, uploaded_by_id=1
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.scalar.return_value = 8 * 1024 * 1024
    monkeypatch.setattr(document_service, "get_storage", lambda: MagicMock())
    file = FakeUploadFile("report.pdf", content=b"x" * (2 * 1024 * 1024))

    result = asyncio.run(document_service.update_document(db, document, file))

    assert result.size_bytes == 2 * 1024 * 1024
    get_settings.cache_clear()
