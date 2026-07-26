"""Tests for the projects router.

Mostly the listing's image handling: GET /projects embeds images, but must not
fall over when an image row can't be loaded - see _project_images.
"""

from datetime import datetime
from unittest.mock import MagicMock

from app.models import Document, Image, ImageStatus, Project, ProjectAccess, ProjectRole
from app.routers import projects as projects_router
from app.routers.projects import _project_full


def _project(**overrides) -> Project:
    now = datetime(2026, 7, 25, 12, 0, 0)
    project = Project(
        **{
            "id": 1,
            "name": "Apollo",
            "description": "Moon landing",
            "owner_id": 1,
            "created_at": now,
            "updated_at": now,
            **overrides,
        }
    )
    return project


def _document() -> Document:
    now = datetime(2026, 7, 25, 12, 0, 0)
    return Document(
        id=1,
        project_id=1,
        filename="a.pdf",
        content_type="application/pdf",
        size_bytes=100,
        storage_key="projects/1/documents/1/a.pdf",
        created_at=now,
        updated_at=now,
    )


def _image() -> Image:
    now = datetime(2026, 7, 25, 12, 0, 0)
    return Image(
        id=1,
        project_id=1,
        filename="pic.jpg",
        content_type="image/jpeg",
        status=ImageStatus.stored,
        size_bytes=500,
        resized_size_bytes=None,
        original_storage_key="projects/1/images/1/original/pic.jpg",
        created_at=now,
        updated_at=now,
    )


class _UnloadableImages:
    """A project whose image rows the current schema can't read - the shape of a
    database that predates a migration."""

    def __init__(self, project: Project):
        object.__setattr__(self, "_project", project)

    def __getattr__(self, name):
        return getattr(self._project, name)

    @property
    def images(self):
        raise RuntimeError("column images.resized_size_bytes does not exist")


def test_project_full_includes_images_normally():
    project = _project()
    project.documents = [_document()]
    project.images = [_image()]

    result = _project_full(MagicMock(), project, ProjectRole.owner)

    assert [image.id for image in result.images] == [1]
    assert [document.id for document in result.documents] == [1]


def test_project_full_omits_images_it_cannot_load_instead_of_raising():
    project = _project()
    project.documents = [_document()]
    db = MagicMock()

    result = _project_full(db, _UnloadableImages(project), ProjectRole.owner)

    # The listing still answers, with the documents intact.
    assert result.images == []
    assert [document.id for document in result.documents] == [1]
    assert result.name == "Apollo"


def test_project_full_rolls_back_after_a_failed_image_load():
    """Without this the aborted transaction would fail every later project too."""
    project = _project()
    project.documents = []
    db = MagicMock()

    _project_full(db, _UnloadableImages(project), ProjectRole.owner)

    db.rollback.assert_called_once()


def test_invite_user_confirms_who_was_invited(monkeypatch):
    """The endpoint answers with a message rather than the project payload, so the
    caller can show it directly."""
    granted = {}

    def _invite(db, access, login):
        granted["login"] = login
        return MagicMock()

    monkeypatch.setattr(projects_router.project_service, "invite_user", _invite)
    access = ProjectAccess(project_id=1, user_id=1, role=ProjectRole.owner)

    result = projects_router.invite_user(user="bob", access=access, db=MagicMock())

    assert result.message == "Invitation sent to bob"
    assert granted["login"] == "bob"  # the access grant still happened
