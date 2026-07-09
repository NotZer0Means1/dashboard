from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.models import Document, User
from app.services.project_service import get_project_access
from app.storage import get_storage

ALLOWED_EXTENSIONS = {".pdf", ".docx"}


def _validate_extension(filename: str | None) -> None:
    extension = Path(filename or "").suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unsupported file type: {extension or 'unknown'}. Only .pdf and .docx are allowed.",
        )


def list_documents(db: Session, project_id: int) -> list[Document]:
    return db.query(Document).filter(Document.project_id == project_id).order_by(Document.id).all()


async def create_documents(
    db: Session, project_id: int, uploader_id: int, files: list[UploadFile]
) -> list[Document]:
    for file in files:
        _validate_extension(file.filename)

    storage = get_storage()
    created: list[Document] = []
    for file in files:
        content = await file.read()
        storage_key = storage.save(project_id, file.filename or "document", content)
        document = Document(
            project_id=project_id,
            filename=file.filename or "document",
            content_type=file.content_type or "application/octet-stream",
            size_bytes=len(content),
            storage_key=storage_key,
            uploaded_by_id=uploader_id,
        )
        db.add(document)
        created.append(document)

    db.commit()
    for document in created:
        db.refresh(document)
    return created


def get_document_for_user(db: Session, document_id: int, user: User) -> Document:
    document = db.query(Document).filter(Document.id == document_id).first()
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    get_project_access(db, document.project_id, user)
    return document


def read_document_content(document: Document) -> bytes:
    return get_storage().read(document.storage_key)


async def update_document(db: Session, document: Document, file: UploadFile) -> Document:
    _validate_extension(file.filename)

    content = await file.read()
    get_storage().overwrite(document.storage_key, content)

    document.filename = file.filename or document.filename
    document.content_type = file.content_type or "application/octet-stream"
    document.size_bytes = len(content)
    db.commit()
    db.refresh(document)
    return document


def delete_document(db: Session, document: Document) -> None:
    get_storage().delete(document.storage_key)
    db.delete(document)
    db.commit()
