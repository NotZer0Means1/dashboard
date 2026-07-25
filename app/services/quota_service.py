from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Document, Image, ImageStatus


def project_bytes_used(db: Session, project_id: int, user_id: int) -> int:
    """Bytes already committed to this project by this user, across documents and images.

    A resized image is charged for both copies: the original is kept as the source
    for future resizes, so it is still occupying storage. Rejected images never count.
    """
    documents = (
        db.query(func.sum(Document.size_bytes))
        .filter(Document.project_id == project_id, Document.uploaded_by_id == user_id)
        .scalar()
    )
    images = (
        db.query(func.sum(Image.size_bytes + func.coalesce(Image.resized_size_bytes, 0)))
        .filter(
            Image.project_id == project_id,
            Image.uploaded_by_id == user_id,
            Image.status != ImageStatus.rejected,
        )
        .scalar()
    )
    return (documents or 0) + (images or 0)


def limit_bytes() -> int:
    return get_settings().max_user_upload_bytes_per_project


def has_room(db: Session, project_id: int, user_id: int, additional_bytes: int) -> bool:
    return project_bytes_used(db, project_id, user_id) + additional_bytes <= limit_bytes()


def enforce_quota(db: Session, project_id: int, user_id: int, additional_bytes: int) -> None:
    limit = limit_bytes()
    used = project_bytes_used(db, project_id, user_id)
    if used + additional_bytes > limit:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"This upload would exceed your {limit // (1024 * 1024)} MB storage limit "
            f"for this project ({used / (1024 * 1024):.1f} MB already used).",
        )
