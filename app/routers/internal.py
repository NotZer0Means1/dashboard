import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_internal_token
from app.schemas import ImageOut, ImageResizeCallback
from app.services import image_service

logger = logging.getLogger(__name__)

# Token auth is declared on the router, not per-endpoint, so anything added here
# is authenticated by construction. Hidden from the public schema.
router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(require_internal_token)],
    include_in_schema=False,
)


@router.post("/images/{image_id}/resize-callback", response_model=ImageOut)
def resize_callback(
    image_id: int,
    payload: ImageResizeCallback,
    db: Session = Depends(get_db),
) -> ImageOut:
    if payload.failed:
        logger.warning("Resize failed for image %s: %s", image_id, payload.error)

    image = image_service.finalize_image(
        db,
        image_id,
        resized_size_bytes=payload.resized_size_bytes,
        width=payload.width,
        height=payload.height,
        failed=payload.failed,
    )
    return ImageOut.model_validate(image)
