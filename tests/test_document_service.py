import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.models import Document, ProjectAccess, ProjectRole, User
from app.services import document_service
from tests.helpers import FakeUploadFile


def test_get_document_for_user_raises_404_when_document_missing():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        document_service.get_document_for_user(db=db, document_id=1, user=User(id=1, login="alice"))

    assert exc_info.value.status_code == 404


def test_get_document_for_user_raises_404_when_no_project_access():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [
        Document(id=1, project_id=1, filename="report.pdf"),
        None,
    ]

    with pytest.raises(HTTPException) as exc_info:
        document_service.get_document_for_user(db=db, document_id=1, user=User(id=1, login="alice"))

    assert exc_info.value.status_code == 404


def test_get_document_for_user_returns_document_when_access_granted():
    document = Document(id=1, project_id=1, filename="report.pdf")
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [
        document,
        ProjectAccess(project_id=1, user_id=1, role=ProjectRole.owner),
    ]

    result = document_service.get_document_for_user(
        db=db, document_id=1, user=User(id=1, login="alice")
    )

    assert result is document


def test_create_documents_raises_413_when_exceeding_quota(db, monkeypatch):
    monkeypatch.setenv("MAX_USER_UPLOAD_BYTES_PER_PROJECT", str(10 * 1024 * 1024))
    db.add(
        Document(
            project_id=1,
            uploaded_by_id=1,
            filename="existing.pdf",
            content_type="application/pdf",
            size_bytes=8 * 1024 * 1024,
            storage_key="1/1/existing.pdf",
        )
    )
    db.commit()
    file = FakeUploadFile("report.pdf", content=b"x" * (3 * 1024 * 1024))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            document_service.create_documents(db, project_id=1, uploader_id=1, files=[file])
        )

    assert exc_info.value.status_code == 413
    assert db.query(Document).count() == 1  # nothing new persisted


def test_create_documents_succeeds_when_within_quota(db, monkeypatch):
    monkeypatch.setenv("MAX_USER_UPLOAD_BYTES_PER_PROJECT", str(10 * 1024 * 1024))
    storage = MagicMock()
    storage.save.return_value = "1/1/report.pdf"
    monkeypatch.setattr(document_service, "get_storage", lambda: storage)
    file = FakeUploadFile("report.pdf", content=b"x" * (1024 * 1024))

    created = asyncio.run(
        document_service.create_documents(db, project_id=1, uploader_id=1, files=[file])
    )

    assert len(created) == 1
    assert created[0].storage_key == "1/1/report.pdf"


def test_create_documents_rejects_unsupported_extension(db):
    file = FakeUploadFile("notes.txt", content=b"x")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            document_service.create_documents(db, project_id=1, uploader_id=1, files=[file])
        )

    assert exc_info.value.status_code == 400


def test_update_document_raises_413_when_replacement_exceeds_quota(db, monkeypatch):
    monkeypatch.setenv("MAX_USER_UPLOAD_BYTES_PER_PROJECT", str(10 * 1024 * 1024))
    document = Document(
        project_id=1,
        uploaded_by_id=1,
        filename="report.pdf",
        content_type="application/pdf",
        size_bytes=8 * 1024 * 1024,
        storage_key="1/1/report.pdf",
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    file = FakeUploadFile("report.pdf", content=b"x" * (11 * 1024 * 1024))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(document_service.update_document(db, document, file))

    assert exc_info.value.status_code == 413


def test_update_document_allows_replacement_within_quota(db, monkeypatch):
    monkeypatch.setenv("MAX_USER_UPLOAD_BYTES_PER_PROJECT", str(10 * 1024 * 1024))
    monkeypatch.setattr(document_service, "get_storage", lambda: MagicMock())
    document = Document(
        project_id=1,
        uploaded_by_id=1,
        filename="report.pdf",
        content_type="application/pdf",
        size_bytes=1 * 1024 * 1024,
        storage_key="1/1/report.pdf",
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    file = FakeUploadFile("report.pdf", content=b"x" * (2 * 1024 * 1024))

    result = asyncio.run(document_service.update_document(db, document, file))

    assert result.size_bytes == 2 * 1024 * 1024
