from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_project_access, require_project_owner
from app.models import Project, ProjectAccess, ProjectRole, User
from app.schemas import (
    DocumentOut,
    ImageOut,
    ProjectCreate,
    ProjectFull,
    ProjectInfo,
    ProjectUpdate,
)
from app.services import project_service

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


def _project_full(project: Project, role: ProjectRole) -> ProjectFull:
    return ProjectFull(
        **_project_info(project, role).model_dump(),
        documents=[DocumentOut.model_validate(document) for document in project.documents],
        images=[ImageOut.model_validate(image) for image in project.images],
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
    return [_project_full(access.project, access.role) for access in accesses]


@router.get("/project/{project_id}/info", response_model=ProjectInfo)
def get_project_info(access: ProjectAccess = Depends(require_project_access)) -> ProjectInfo:
    return _project_info(access.project, access.role)


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
    "/project/{project_id}/invite", response_model=ProjectInfo, status_code=status.HTTP_201_CREATED
)
def invite_user(
    user: str = Query(..., description="Login of the user to grant access to"),
    access: ProjectAccess = Depends(require_project_owner),
    db: Session = Depends(get_db),
) -> ProjectInfo:
    project_service.invite_user(db, access, user)
    return _project_info(access.project, access.role)
