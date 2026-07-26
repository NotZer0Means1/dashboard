from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.image_storage import build_original_key, build_resized_key, get_image_storage
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
    """Stores the upload in S3 and returns it with status=stored.

    No resizing happens here, but the PUT below is what triggers it: the bucket
    has an ObjectCreated notification on the originals prefix, so the resize
    Lambda fires asynchronously and reports back to finalize_image() later. The
    row is therefore returned as "stored" and flips to "ready" out of band.
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

    # The object must not exist before the row does: the PUT fires the S3
    # notification, and the Lambda's callback looks the row up by image_id.
    # Committing first means that callback can never lose the race and 404 on an
    # image that is still halfway through being created. The key is deterministic,
    # so it can be recorded before the bytes are actually uploaded.
    image.original_storage_key = build_original_key(project_id, image.id, filename)
    db.commit()

    get_image_storage().save_original(project_id, image.id, filename, content)

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

    The resized copy always lives at the same deterministic key, so a redelivered
    S3 event overwrites the previous one rather than accumulating - only the
    difference in size is charged, which also makes a duplicate callback harmless.
    """
    previous = image.resized_size_bytes or 0
    delta = resized_size_bytes - previous

    if image.uploaded_by_id is not None and not quota_service.has_room(
        db, image.project_id, image.uploaded_by_id, delta
    ):
        # The Lambda has already written the object at resized_key, so delete it
        # and drop back to "stored": the row then matches storage instead of
        # pointing at bytes that are over quota. The original is untouched and
        # still downloadable, so the image stays usable at full size.
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


def finalize_image(
    db: Session,
    image_id: int,
    *,
    resized_size_bytes: int | None = None,
    width: int | None = None,
    height: int | None = None,
    failed: bool = False,
) -> Image:
    """Records the outcome of a resize, called from the Lambda's callback.

    This is the only path that promotes an image to "ready": the resize runs
    asynchronously off an S3 event, long after the upload request has returned,
    so the function reports back here instead of the app waiting on it.

    The resized object is already in S3 by the time this runs - the Lambda writes
    it before calling back - so the key is rebuilt rather than passed in.
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


def read_image_content(image: Image, *, original: bool = False) -> bytes:
    """Serves the resized copy once one exists, and the original until then.

    An unresized image is a normal, downloadable image - only a rejected one has
    nothing usable to serve.

    original=True asks for the full-size upload regardless of whether a resized
    copy exists. It is kept after a resize and charged against quota (see
    quota_service), so this is what makes that charge honest - otherwise the
    project pays for bytes nothing can reach.
    """
    if image.status == ImageStatus.rejected:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Image was rejected and has no usable content."
        )
    if original:
        key = image.original_storage_key
    else:
        key = image.storage_key or image.original_storage_key
    if not key:
        raise HTTPException(status.HTTP_409_CONFLICT, "Image has no stored content.")
    return get_image_storage().read(key)


def delete_image(db: Session, image: Image, *, copy: str = "all") -> None:
    """Deletes the whole image, or just one of its two stored copies.

    A resized image occupies S3 twice and is charged for both (see quota_service),
    so either copy may be the one worth freeing: drop the resized copy to go back
    to serving the full-size original, or drop the original once the resized copy
    is the only one you still need. "all" removes both objects and the row.

    Nothing re-resizes an image - that only happens on upload - so deleting the
    resized copy is a one-way door, not a step in a re-resize.
    """
    storage = get_image_storage()

    if copy == "resized":
        if not image.storage_key:
            raise HTTPException(status.HTTP_409_CONFLICT, "Image has no resized copy to delete.")
        storage.delete(image.storage_key)
        image.storage_key = None
        image.resized_size_bytes = None
        image.width = None
        image.height = None
        image.status = ImageStatus.stored
        db.commit()
        return

    if copy == "original":
        if not image.original_storage_key:
            raise HTTPException(status.HTTP_409_CONFLICT, "Image has no stored original to delete.")
        if not image.storage_key:
            # Would leave a row that can serve nothing at all. Deleting the whole
            # image is the honest way to express that.
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Deleting the original would leave nothing to serve. Delete the image instead.",
            )
        storage.delete(image.original_storage_key)
        image.original_storage_key = ""
        # The bytes are gone, so the project must stop being charged for them.
        image.size_bytes = 0
        db.commit()
        return

    if image.original_storage_key:
        storage.delete(image.original_storage_key)
    if image.storage_key:
        storage.delete(image.storage_key)
    db.delete(image)
    db.commit()
