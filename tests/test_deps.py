from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.deps import _get_project_access, require_project_owner
from app.models import ProjectAccess, ProjectRole, User


def _db_returning(value):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = value
    return db


def test_get_project_access_raises_404_when_missing():
    user = User(id=1, login="alice")

    with pytest.raises(HTTPException) as exc_info:
        _get_project_access(project_id=1, user=user, db=_db_returning(None))

    assert exc_info.value.status_code == 404


def test_get_project_access_returns_existing_access():
    access = ProjectAccess(project_id=1, user_id=1, role=ProjectRole.owner)
    user = User(id=1, login="alice")

    result = _get_project_access(project_id=1, user=user, db=_db_returning(access))

    assert result is access


def test_require_project_owner_raises_403_for_participant():
    access = ProjectAccess(project_id=1, user_id=2, role=ProjectRole.participant)
    user = User(id=2, login="bob")

    with pytest.raises(HTTPException) as exc_info:
        require_project_owner(project_id=1, user=user, db=_db_returning(access))

    assert exc_info.value.status_code == 403


def test_require_project_owner_allows_owner():
    access = ProjectAccess(project_id=1, user_id=1, role=ProjectRole.owner)
    user = User(id=1, login="alice")

    result = require_project_owner(project_id=1, user=user, db=_db_returning(access))

    assert result is access
