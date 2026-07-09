from fastapi import APIRouter, Depends, File, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, get_document_for_user, require_project_access
from app.models import Document, ProjectAccess, User
from app.schemas import DocumentOut
from app.services import document_service

router = APIRouter(tags=["documents"])


def _content_disposition(filename: str) -> str:
    safe_name = filename.replace("\r", "").replace("\n", "").replace('"', "")
    return f'attachment; filename="{safe_name}"'


@router.get("/project/{project_id}/documents", response_model=list[DocumentOut])
def list_documents(
    access: ProjectAccess = Depends(require_project_access),
    db: Session = Depends(get_db),
) -> list[DocumentOut]:
    documents = document_service.list_documents(db, access.project_id)
    return [DocumentOut.model_validate(document) for document in documents]


@router.post(
    "/project/{project_id}/documents",
    response_model=list[DocumentOut],
    status_code=status.HTTP_201_CREATED,
)
async def upload_documents(
    files: list[UploadFile] = File(...),
    access: ProjectAccess = Depends(require_project_access),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DocumentOut]:
    documents = await document_service.create_documents(db, access.project_id, user.id, files)
    return [DocumentOut.model_validate(document) for document in documents]


@router.get("/document/{document_id}")
def download_document(document: Document = Depends(get_document_for_user)) -> Response:
    content = document_service.read_document_content(document)
    return Response(
        content=content,
        media_type=document.content_type,
        headers={"Content-Disposition": _content_disposition(document.filename)},
    )


@router.put("/document/{document_id}", response_model=DocumentOut)
async def update_document(
    file: UploadFile = File(...),
    document: Document = Depends(get_document_for_user),
    db: Session = Depends(get_db),
) -> DocumentOut:
    document = await document_service.update_document(db, document, file)
    return DocumentOut.model_validate(document)


@router.delete("/document/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document: Document = Depends(get_document_for_user),
    db: Session = Depends(get_db),
) -> None:
    document_service.delete_document(db, document)
