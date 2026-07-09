from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.models import Document, ProjectAccess, ProjectRole, User
from app.services import document_service


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
