import pytest
from pydantic import ValidationError

from app.schemas import ProjectCreate, UserCreate


def test_user_create_accepts_matching_passwords():
    user = UserCreate(login="alice", password="hunter2222", repeat_password="hunter2222")
    assert user.login == "alice"


def test_user_create_rejects_mismatched_passwords():
    with pytest.raises(ValidationError):
        UserCreate(login="alice", password="hunter2222", repeat_password="other-pass")


def test_user_create_rejects_short_login():
    with pytest.raises(ValidationError):
        UserCreate(login="ab", password="hunter2222", repeat_password="hunter2222")


def test_project_create_allows_optional_description():
    project = ProjectCreate(name="Apollo")
    assert project.description is None
