import logging

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_project_access, require_project_owner
from app.models import Project, ProjectAccess, ProjectRole, User
from app.schemas import (
    DocumentOut,
    ImageOut,
    InviteOut,
    ProjectCreate,
    ProjectFull,
    ProjectInfo,
    ProjectUpdate,
)
from app.services import project_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["projects"])


def _project_info(project: Project, role: ProjectRole) -> ProjectInfo:
    return ProjectInfo(
        id=project.id,
        name=project.name,
        description=project.description,
        owner_id=project.owner_id,
        role=role.value,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def _project_images(db: Session, project: Project) -> list[ImageOut]:
    """Images are best-effort here: a row this schema can't load - one written
    before a migration, say - degrades to an omitted image instead of a 500 for
    the whole listing. Broad except on purpose: the failure can come from the
    lazy load (SQLAlchemy) or the validation (Pydantic), which share no base class.

    GET /project/{id}/images is the unforgiving version - use it to see the real
    error when images go missing from here.
    """
    try:
        return [ImageOut.model_validate(image) for image in project.images]
    except Exception:
        logger.warning("Skipping unloadable images for project %s", project.id, exc_info=True)
        # A failed statement leaves the transaction unusable on Postgres, so the
        # remaining projects would fail too without this. Safe: the listing is
        # read-only, so there is nothing pending to lose.
        db.rollback()
        return []


def _project_full(db: Session, project: Project, role: ProjectRole) -> ProjectFull:
    # Argument order matters: info and documents are built before the images call
    # can trigger a rollback, so they can't be caught half-built by it.
    return ProjectFull(
        **_project_info(project, role).model_dump(),
        documents=[DocumentOut.model_validate(document) for document in project.documents],
        images=_project_images(db, project),
    )


@router.post("/projects", response_model=ProjectInfo, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectInfo:
    project = project_service.create_project(db, user, payload.name, payload.description)
    return _project_info(project, ProjectRole.owner)


@router.get("/projects", response_model=list[ProjectFull])
def list_projects(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ProjectFull]:
    accesses = project_service.list_accesses_for_user(db, user)
    return [_project_full(db, access.project, access.role) for access in accesses]


@router.put("/project/{project_id}/info", response_model=ProjectInfo)
def update_project_info(
    payload: ProjectUpdate,
    access: ProjectAccess = Depends(require_project_access),
    db: Session = Depends(get_db),
) -> ProjectInfo:
    project = project_service.update_project_info(
        db, access.project, payload.name, payload.description
    )
    return _project_info(project, access.role)


@router.delete("/project/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    access: ProjectAccess = Depends(require_project_owner),
    db: Session = Depends(get_db),
) -> None:
    project_service.delete_project(db, access.project)


@router.post(
    "/project/{project_id}/invite", response_model=InviteOut, status_code=status.HTTP_201_CREATED
)
def invite_user(
    user: str = Query(..., description="Login of the user to grant access to"),
    access: ProjectAccess = Depends(require_project_owner),
    db: Session = Depends(get_db),
) -> InviteOut:
    project_service.invite_user(db, access, user)
    # The lookup is an exact match on login, so echoing the query value back names
    # the user who was actually granted access.
    return InviteOut(message=f"Invitation sent to {user}")
