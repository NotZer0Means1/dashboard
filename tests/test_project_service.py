from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.models import ProjectAccess, ProjectRole, User
from app.services import project_service


def _db_returning(value):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = value
    return db


def test_get_project_access_raises_404_when_missing():
    user = User(id=1, login="alice")

    with pytest.raises(HTTPException) as exc_info:
        project_service.get_project_access(db=_db_returning(None), project_id=1, user=user)

    assert exc_info.value.status_code == 404


def test_get_project_access_returns_existing_access():
    access = ProjectAccess(project_id=1, user_id=1, role=ProjectRole.owner)
    user = User(id=1, login="alice")

    result = project_service.get_project_access(db=_db_returning(access), project_id=1, user=user)

    assert result is access


def test_require_owner_raises_403_for_participant():
    access = ProjectAccess(project_id=1, user_id=2, role=ProjectRole.participant)

    with pytest.raises(HTTPException) as exc_info:
        project_service.require_owner(access)

    assert exc_info.value.status_code == 403


def test_require_owner_allows_owner():
    access = ProjectAccess(project_id=1, user_id=1, role=ProjectRole.owner)

    result = project_service.require_owner(access)

    assert result is access


def test_invite_user_raises_404_when_invitee_missing():
    access = ProjectAccess(project_id=1, user_id=1, role=ProjectRole.owner)
    db = _db_returning(None)

    with pytest.raises(HTTPException) as exc_info:
        project_service.invite_user(db, access, "bob")

    assert exc_info.value.status_code == 404


def test_invite_user_raises_409_when_already_has_access():
    access = ProjectAccess(project_id=1, user_id=1, role=ProjectRole.owner)
    invitee = User(id=2, login="bob")
    existing_access = ProjectAccess(project_id=1, user_id=2, role=ProjectRole.participant)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [invitee, existing_access]

    with pytest.raises(HTTPException) as exc_info:
        project_service.invite_user(db, access, "bob")

    assert exc_info.value.status_code == 409


def test_invite_user_grants_participant_access():
    access = ProjectAccess(project_id=1, user_id=1, role=ProjectRole.owner)
    invitee = User(id=2, login="bob")
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [invitee, None]

    new_access = project_service.invite_user(db, access, "bob")

    assert new_access.project_id == 1
    assert new_access.user_id == 2
    assert new_access.role == ProjectRole.participant
    db.add.assert_called_once_with(new_access)
    db.commit.assert_called_once()
