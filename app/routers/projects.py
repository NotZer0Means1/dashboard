from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.deps import get_current_user, require_project_access, require_project_owner
from app.models import Project, ProjectAccess, ProjectRole, User
from app.schemas import DocumentOut, ProjectCreate, ProjectFull, ProjectInfo, ProjectUpdate
from app.storage import get_storage

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
    )


@router.post("/projects", response_model=ProjectInfo, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectInfo:
    project = Project(name=payload.name, description=payload.description, owner_id=user.id)
    db.add(project)
    db.flush()

    db.add(ProjectAccess(project_id=project.id, user_id=user.id, role=ProjectRole.owner))
    db.commit()
    db.refresh(project)
    return _project_info(project, ProjectRole.owner)


@router.get("/projects", response_model=list[ProjectFull])
def list_projects(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ProjectFull]:
    accesses = (
        db.query(ProjectAccess)
        .filter(ProjectAccess.user_id == user.id)
        .options(joinedload(ProjectAccess.project).joinedload(Project.documents))
        .all()
    )
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
    project = access.project
    project.name = payload.name
    project.description = payload.description
    db.commit()
    db.refresh(project)
    return _project_info(project, access.role)


@router.delete("/project/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    access: ProjectAccess = Depends(require_project_owner),
    db: Session = Depends(get_db),
) -> None:
    project = access.project
    get_storage().delete_project_dir(project.id)
    db.delete(project)
    db.commit()


@router.post(
    "/project/{project_id}/invite", response_model=ProjectInfo, status_code=status.HTTP_201_CREATED
)
def invite_user(
    user: str = Query(..., description="Login of the user to grant access to"),
    access: ProjectAccess = Depends(require_project_owner),
    db: Session = Depends(get_db),
) -> ProjectInfo:
    invitee = db.query(User).filter(User.login == user).first()
    if invitee is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    existing = (
        db.query(ProjectAccess)
        .filter(ProjectAccess.project_id == access.project_id, ProjectAccess.user_id == invitee.id)
        .first()
    )
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "User already has access to this project")

    new_access = ProjectAccess(
        project_id=access.project_id, user_id=invitee.id, role=ProjectRole.participant
    )
    db.add(new_access)
    db.commit()
    return _project_info(access.project, access.role)
