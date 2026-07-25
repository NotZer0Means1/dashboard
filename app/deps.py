from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Document, Image, ProjectAccess, User
from app.security import decode_access_token
from app.services import document_service, image_service, project_service, user_service

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
    user = user_service.get_user_by_login(db, login)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return user


def require_project_access(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectAccess:
    return project_service.get_project_access(db, project_id, user)


def require_project_owner(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectAccess:
    access = project_service.get_project_access(db, project_id, user)
    return project_service.require_owner(access)


def get_document_for_user(
    document_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Document:
    return document_service.get_document_for_user(db, document_id, user)


def get_image_for_user(
    image_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Image:
    return image_service.get_image_for_user(db, image_id, user)
