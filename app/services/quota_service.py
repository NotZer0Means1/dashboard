from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Document, Image, ImageStatus


def project_bytes_used(db: Session, project_id: int, user_id: int) -> int:
    """Bytes already committed to this project by this user, across documents and images.

    A pending image's reserved (original) size counts here too, so two concurrent
    uploads can't each individually pass the check and jointly blow the limit.
    Rejected images never count.
    """
    documents = (
        db.query(func.sum(Document.size_bytes))
        .filter(Document.project_id == project_id, Document.uploaded_by_id == user_id)
        .scalar()
    )
    images = (
        db.query(func.sum(Image.size_bytes))
        .filter(
            Image.project_id == project_id,
            Image.uploaded_by_id == user_id,
            Image.status != ImageStatus.rejected,
        )
        .scalar()
    )
    return (documents or 0) + (images or 0)


def has_room(db: Session, project_id: int, user_id: int, additional_bytes: int) -> bool:
    limit = get_settings().max_user_upload_bytes_per_project
    return project_bytes_used(db, project_id, user_id) + additional_bytes <= limit


def enforce_quota(db: Session, project_id: int, user_id: int, additional_bytes: int) -> None:
    limit = get_settings().max_user_upload_bytes_per_project
    used = project_bytes_used(db, project_id, user_id)
    if used + additional_bytes > limit:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"This upload would exceed your {limit // (1024 * 1024)} MB storage limit "
            f"for this project ({used / (1024 * 1024):.1f} MB already used).",
        )
