from fastapi import APIRouter, Depends, File, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, get_image_for_user, require_project_access
from app.models import Image, ProjectAccess, User
from app.routers._helpers import attachment_response
from app.schemas import ImageOut
from app.services import image_service

router = APIRouter(tags=["images"])


@router.get("/project/{project_id}/images", response_model=list[ImageOut])
def list_images(
    access: ProjectAccess = Depends(require_project_access),
    db: Session = Depends(get_db),
) -> list[ImageOut]:
    images = image_service.list_images(db, access.project_id)
    return [ImageOut.model_validate(image) for image in images]


@router.post(
    "/project/{project_id}/images",
    response_model=ImageOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_image(
    file: UploadFile = File(...),
    access: ProjectAccess = Depends(require_project_access),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ImageOut:
    image = await image_service.create_image(db, access.project_id, user.id, file)
    return ImageOut.model_validate(image)


@router.get("/image/{image_id}/info", response_model=ImageOut)
def get_image_info(image: Image = Depends(get_image_for_user)) -> ImageOut:
    """Poll this after uploading: resizing runs asynchronously off an S3 event,
    so status flips from "stored" to "ready" some time after the upload returns."""
    return ImageOut.model_validate(image)


@router.get("/image/{image_id}")
def download_image(image: Image = Depends(get_image_for_user)) -> Response:
    content = image_service.read_image_content(image)
    return attachment_response(content, image.content_type, image.filename)


@router.delete("/image/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_image(
    image: Image = Depends(get_image_for_user),
    db: Session = Depends(get_db),
) -> None:
    image_service.delete_image(db, image)
