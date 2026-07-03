from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, get_document_for_user, require_project_access
from app.models import Document, ProjectAccess, User
from app.schemas import DocumentOut
from app.storage import get_storage

router = APIRouter(tags=["documents"])

ALLOWED_EXTENSIONS = {".pdf", ".docx"}


def _validate_extension(filename: str | None) -> None:
    extension = Path(filename or "").suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unsupported file type: {extension or 'unknown'}. Only .pdf and .docx are allowed.",
        )


def _content_disposition(filename: str) -> str:
    safe_name = filename.replace("\r", "").replace("\n", "").replace('"', "")
    return f'attachment; filename="{safe_name}"'


@router.get("/project/{project_id}/documents", response_model=list[DocumentOut])
def list_documents(access: ProjectAccess = Depends(require_project_access)) -> list[DocumentOut]:
    return [DocumentOut.model_validate(document) for document in access.project.documents]


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
    for file in files:
        _validate_extension(file.filename)

    storage = get_storage()
    created: list[Document] = []
    for file in files:
        content = await file.read()
        storage_key = storage.save(access.project_id, file.filename or "document", content)
        document = Document(
            project_id=access.project_id,
            filename=file.filename or "document",
            content_type=file.content_type or "application/octet-stream",
            size_bytes=len(content),
            storage_key=storage_key,
            uploaded_by_id=user.id,
        )
        db.add(document)
        created.append(document)

    db.commit()
    for document in created:
        db.refresh(document)
    return [DocumentOut.model_validate(document) for document in created]


@router.get("/document/{document_id}")
def download_document(document: Document = Depends(get_document_for_user)) -> Response:
    content = get_storage().read(document.storage_key)
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
    _validate_extension(file.filename)

    content = await file.read()
    get_storage().overwrite(document.storage_key, content)

    document.filename = file.filename or document.filename
    document.content_type = file.content_type or "application/octet-stream"
    document.size_bytes = len(content)
    db.commit()
    db.refresh(document)
    return DocumentOut.model_validate(document)


@router.delete("/document/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document: Document = Depends(get_document_for_user),
    db: Session = Depends(get_db),
) -> None:
    get_storage().delete(document.storage_key)
    db.delete(document)
    db.commit()
