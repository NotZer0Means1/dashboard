from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.image_storage import build_resized_key, get_image_storage
from app.image_validation import InvalidImageError, validate_image
from app.lambda_client import ResizeInvocationError, get_resize_lambda_client
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
    """Stores the upload in S3 and returns it with status=stored.

    Nothing is resized here and no Lambda runs: resizing is an explicit,
    user-triggered step (see resize_image). An image that is never resized stays
    "stored" indefinitely, which is a perfectly normal end state.
    """
    content_type = _validate_and_normalize_content_type(file.filename)
    content = await file.read()
    try:
        validate_image(content)
    except InvalidImageError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Invalid or corrupted image file."
        ) from exc

    quota_service.enforce_quota(db, project_id, uploader_id, len(content))

    filename = file.filename or "image"
    image = Image(
        project_id=project_id,
        filename=filename,
        content_type=content_type,
        status=ImageStatus.stored,
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


def _apply_resize_result(
    db: Session,
    image: Image,
    *,
    resized_key: str,
    resized_size_bytes: int,
    width: int | None,
    height: int | None,
) -> Image:
    """Records a completed resize against the image, enforcing quota on the way in.

    The resized copy always lives at the same deterministic key, so a re-resize
    overwrites the previous one - only the difference in size is charged.
    """
    previous = image.resized_size_bytes or 0
    delta = resized_size_bytes - previous

    if image.uploaded_by_id is not None and not quota_service.has_room(
        db, image.project_id, image.uploaded_by_id, delta
    ):
        # The Lambda has already overwritten the object at resized_key, so the
        # previous resized copy (if any) is gone and can't be restored. Drop back
        # to "stored" so the row matches storage instead of pointing at bytes
        # that no longer exist - the original is untouched, so a smaller resize
        # can simply be requested again.
        get_image_storage().delete(resized_key)
        image.status = ImageStatus.stored
        image.resized_size_bytes = None
        image.storage_key = None
        image.width = None
        image.height = None
        db.commit()
        limit_mb = quota_service.limit_bytes() // (1024 * 1024)
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"The resized image would exceed your {limit_mb} MB storage limit "
            f"for this project. Try smaller dimensions.",
        )

    image.status = ImageStatus.ready
    image.resized_size_bytes = resized_size_bytes
    image.storage_key = resized_key
    image.width = width
    image.height = height
    db.commit()
    db.refresh(image)
    return image


def resize_image(db: Session, image: Image, *, width: int, height: int) -> Image:
    """Invokes the resize Lambda synchronously and applies its result.

    The original is kept as the resize source, so this can be re-run at different
    dimensions without compounding quality loss. Both copies count against quota.
    """
    if not image.original_storage_key:
        raise HTTPException(status.HTTP_409_CONFLICT, "Image has no stored original to resize.")

    storage = get_image_storage()
    resized_key = build_resized_key(image.project_id, image.id, image.filename)

    try:
        result = get_resize_lambda_client().resize(
            bucket=storage.bucket,
            source_key=image.original_storage_key,
            target_key=resized_key,
            filename=image.filename,
            width=width,
            height=height,
        )
    except ResizeInvocationError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Resize service unavailable: {exc}"
        ) from exc

    if not result.ok:
        # The Lambda couldn't decode the stored original. Terminal for this image:
        # retrying would fail the same way, so mark it rather than leave it looking
        # resizable. The original is kept so it can still be downloaded.
        image.status = ImageStatus.rejected
        db.commit()
        db.refresh(image)
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Image could not be resized: {result.error}",
        )

    return _apply_resize_result(
        db,
        image,
        resized_key=resized_key,
        resized_size_bytes=result.resized_size_bytes,
        width=result.width,
        height=result.height,
    )


def finalize_image(
    db: Session,
    image_id: int,
    *,
    resized_size_bytes: int | None = None,
    width: int | None = None,
    height: int | None = None,
    failed: bool = False,
) -> Image:
    """Records a resize performed outside the normal request path.

    Nothing calls this automatically any more - resize_image() invokes the Lambda
    synchronously and applies the result itself. It stays as a manual override for
    the case where a resize was run out-of-band (see the Internal folder of
    postman_collection.json) and the row needs to catch up.
    """
    image = db.query(Image).filter(Image.id == image_id).first()
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")

    if failed:
        image.status = ImageStatus.rejected
        db.commit()
        db.refresh(image)
        return image

    if resized_size_bytes is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "resized_size_bytes is required when failed=false"
        )

    return _apply_resize_result(
        db,
        image,
        resized_key=build_resized_key(image.project_id, image.id, image.filename),
        resized_size_bytes=resized_size_bytes,
        width=width,
        height=height,
    )


def list_images(db: Session, project_id: int) -> list[Image]:
    return db.query(Image).filter(Image.project_id == project_id).order_by(Image.id).all()


def get_image_for_user(db: Session, image_id: int, user: User) -> Image:
    image = db.query(Image).filter(Image.id == image_id).first()
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")
    get_project_access(db, image.project_id, user)
    return image


def read_image_content(image: Image) -> bytes:
    """Serves the resized copy once one exists, and the original until then.

    An unresized image is a normal, downloadable image - only a rejected one has
    nothing usable to serve.
    """
    if image.status == ImageStatus.rejected:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Image was rejected and has no usable content."
        )
    key = image.storage_key or image.original_storage_key
    if not key:
        raise HTTPException(status.HTTP_409_CONFLICT, "Image has no stored content.")
    return get_image_storage().read(key)


def delete_image(db: Session, image: Image) -> None:
    storage = get_image_storage()
    if image.original_storage_key:
        storage.delete(image.original_storage_key)
    if image.storage_key:
        storage.delete(image.storage_key)
    db.delete(image)
    db.commit()
