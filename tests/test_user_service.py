from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.models import User
from app.security import hash_password
from app.services import user_service


def _db_returning(value):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = value
    return db


def test_get_user_by_login_returns_none_when_missing():
    result = user_service.get_user_by_login(db=_db_returning(None), login="alice")
    assert result is None


def test_create_user_raises_409_on_duplicate_login():
    existing = User(id=1, login="alice", hashed_password="hash")

    with pytest.raises(HTTPException) as exc_info:
        user_service.create_user(db=_db_returning(existing), login="alice", password="hunter2222")

    assert exc_info.value.status_code == 409


def test_authenticate_user_raises_401_when_user_missing():
    with pytest.raises(HTTPException) as exc_info:
        user_service.authenticate_user(db=_db_returning(None), login="alice", password="hunter2222")

    assert exc_info.value.status_code == 401


def test_authenticate_user_raises_401_on_wrong_password():
    existing = User(id=1, login="alice", hashed_password=hash_password("correct-password"))

    with pytest.raises(HTTPException) as exc_info:
        user_service.authenticate_user(
            db=_db_returning(existing), login="alice", password="wrong-password"
        )

    assert exc_info.value.status_code == 401


def test_authenticate_user_returns_user_on_success():
    existing = User(id=1, login="alice", hashed_password=hash_password("correct-password"))

    result = user_service.authenticate_user(
        db=_db_returning(existing), login="alice", password="correct-password"
    )

    assert result is existing
