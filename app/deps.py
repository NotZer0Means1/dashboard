from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Document, ProjectAccess, ProjectRole, User
from app.security import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    login = decode_access_token(credentials.credentials)
    if login is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = db.query(User).filter(User.login == login).first()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return user


def _get_project_access(project_id: int, user: User, db: Session) -> ProjectAccess:
    access = (
        db.query(ProjectAccess)
        .filter(ProjectAccess.project_id == project_id, ProjectAccess.user_id == user.id)
        .first()
    )
    if access is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return access


def require_project_access(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectAccess:
    return _get_project_access(project_id, user, db)


def require_project_owner(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectAccess:
    access = _get_project_access(project_id, user, db)
    if access.role != ProjectRole.owner:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the project owner can perform this action"
        )
    return access


def get_document_for_user(
    document_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Document:
    document = db.query(Document).filter(Document.id == document_id).first()
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    _get_project_access(document.project_id, user, db)
    return document
