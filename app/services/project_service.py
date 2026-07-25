from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.image_storage import get_image_storage
from app.models import Project, ProjectAccess, ProjectRole, User
from app.services import user_service
from app.storage import get_storage


def get_project_access(db: Session, project_id: int, user: User) -> ProjectAccess:
    access = (
        db.query(ProjectAccess)
        .filter(ProjectAccess.project_id == project_id, ProjectAccess.user_id == user.id)
        .first()
    )
    if access is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return access


def require_owner(access: ProjectAccess) -> ProjectAccess:
    if access.role != ProjectRole.owner:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the project owner can perform this action"
        )
    return access


def create_project(db: Session, owner: User, name: str, description: str | None) -> Project:
    project = Project(name=name, description=description, owner_id=owner.id)
    db.add(project)
    db.flush()

    db.add(ProjectAccess(project_id=project.id, user_id=owner.id, role=ProjectRole.owner))
    db.commit()
    db.refresh(project)
    return project


def list_accesses_for_user(db: Session, user: User) -> list[ProjectAccess]:
    return (
        db.query(ProjectAccess)
        .filter(ProjectAccess.user_id == user.id)
        # selectinload, not joinedload: joining two sibling collections in one
        # query multiplies rows (documents x images per project).
        .options(
            joinedload(ProjectAccess.project).selectinload(Project.documents),
            joinedload(ProjectAccess.project).selectinload(Project.images),
        )
        .all()
    )


def update_project_info(
    db: Session, project: Project, name: str, description: str | None
) -> Project:
    project.name = name
    project.description = description
    db.commit()
    db.refresh(project)
    return project


def _delete_project_storage(project_id: int) -> None:
    """Every store holding bytes for a project. A new asset type belongs here -
    the DB rows cascade away on their own, but orphaned objects leak silently."""
    get_storage().delete_project_dir(project_id)
    get_image_storage().delete_project_images(project_id)


def delete_project(db: Session, project: Project) -> None:
    _delete_project_storage(project.id)
    db.delete(project)
    db.commit()


def invite_user(db: Session, access: ProjectAccess, invitee_login: str) -> ProjectAccess:
    invitee = user_service.get_user_by_login(db, invitee_login)
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
    db.refresh(new_access)
    return new_access
