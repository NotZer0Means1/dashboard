from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.image_storage import build_resized_key, get_image_storage
from app.image_validation import InvalidImageError, validate_image
from app.models import Image, ImageStatus, User
from app.services import quota_service
from app.services.project_service import get_project_access

ALLOWED_EXTENSIONS = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def _validate_and_normalize_content_type(filename: str | None) -> str:
    extension = Path(filename or "").suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unsupported image type: {extension or 'unknown'}. "
            f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}.",
        )
    return ALLOWED_EXTENSIONS[extension]


async def create_image(db: Session, project_id: int, uploader_id: int, file: UploadFile) -> Image:
    """Uploads the original to S3 and returns immediately with status=pending.
    An S3 event notification (see infra/aws/README.md) fires the resize Lambda,
    which downloads the original, resizes it, uploads the result under the
    resized/ prefix, and POSTs back to finalize_image() with the outcome.
    """
    content_type = _validate_and_normalize_content_type(file.filename)
    content = await file.read()
    try:
        validate_image(content)
    except InvalidImageError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Invalid or corrupted image file."
        ) from exc

    # Preliminary gate on the raw upload, which also reserves these bytes
    # against quota for the pending window - otherwise two concurrent
    # uploads could each pass the check individually and blow the limit
    # together. finalize_image() settles up against the real, resized size.
    quota_service.enforce_quota(db, project_id, uploader_id, len(content))

    filename = file.filename or "image"
    image = Image(
        project_id=project_id,
        filename=filename,
        content_type=content_type,
        status=ImageStatus.pending,
        size_bytes=len(content),
        original_storage_key="",
        storage_key=None,
        uploaded_by_id=uploader_id,
    )
    db.add(image)
    db.flush()  # assign image.id before it's used to build the storage key

    image.original_storage_key = get_image_storage().save_original(
        project_id, image.id, filename, content
    )

    db.commit()
    db.refresh(image)
    return image


def finalize_image(
    db: Session,
    image_id: int,
    *,
    resized_size_bytes: int | None = None,
    width: int | None = None,
    height: int | None = None,
    failed: bool = False,
) -> Image:
    """Called by the resize Lambda's callback once it's done with the original -
    successfully or not. Settles the quota against the real (resized) size and
    either promotes the image to ready or rejects it and cleans up storage.
    failed=True (the Lambda couldn't decode the original, etc.) rejects it the
    same way a quota miss does, so a bad upload never sits in "pending" forever.
    Idempotent: a retried/duplicate callback for an already-resolved image is a no-op.
    """
    image = db.query(Image).filter(Image.id == image_id).first()
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")
    if image.status != ImageStatus.pending:
        return image

    storage = get_image_storage()
    resized_key = build_resized_key(image.project_id, image.id, image.filename)

    if not failed and resized_size_bytes is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "resized_size_bytes is required when failed=false"
        )

    delta = (resized_size_bytes - image.size_bytes) if resized_size_bytes is not None else 0
    rejected = failed or (
        image.uploaded_by_id is not None
        and not quota_service.has_room(db, image.project_id, image.uploaded_by_id, delta)
    )

    storage.delete(image.original_storage_key)
    if rejected:
        storage.delete(resized_key)
        image.status = ImageStatus.rejected
    else:
        image.status = ImageStatus.ready
        image.size_bytes = resized_size_bytes
        image.storage_key = resized_key
        image.width = width
        image.height = height

    db.commit()
    db.refresh(image)
    return image


def list_images(db: Session, project_id: int) -> list[Image]:
    return db.query(Image).filter(Image.project_id == project_id).order_by(Image.id).all()


def get_image_for_user(db: Session, image_id: int, user: User) -> Image:
    image = db.query(Image).filter(Image.id == image_id).first()
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")
    get_project_access(db, image.project_id, user)
    return image


def read_image_content(image: Image) -> bytes:
    if image.status != ImageStatus.ready or image.storage_key is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Image is not ready yet (status: {image.status.value}).",
        )
    return get_image_storage().read(image.storage_key)


def delete_image(db: Session, image: Image) -> None:
    storage = get_image_storage()
    if image.original_storage_key:
        storage.delete(image.original_storage_key)
    if image.storage_key:
        storage.delete(image.storage_key)
    db.delete(image)
    db.commit()
