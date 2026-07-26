import enum
from datetime import datetime

from sqlalchemy import Enum as SqlEnum
from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ProjectRole(enum.StrEnum):
    owner = "owner"
    participant = "participant"


class ImageStatus(enum.StrEnum):
    # Set at upload. Resizing runs asynchronously off an S3 event, so this is a
    # waiting room: the callback promotes the row to "ready" once the Lambda has
    # written the resized copy. A row stuck here means the function never
    # reported back - check its CloudWatch logs.
    stored = "stored"
    ready = "ready"
    rejected = "rejected"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(150), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    project_accesses: Mapped[list["ProjectAccess"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    owner: Mapped["User"] = relationship()
    accesses: Mapped[list["ProjectAccess"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    documents: Mapped[list["Document"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    images: Mapped[list["Image"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ProjectAccess(Base):
    __tablename__ = "project_access"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[ProjectRole] = mapped_column(
        SqlEnum(ProjectRole, native_enum=False, length=20),
        nullable=False,
        default=ProjectRole.participant,
    )
    granted_at: Mapped[datetime] = mapped_column(server_default=func.now())

    project: Mapped["Project"] = relationship(back_populates="accesses")
    user: Mapped["User"] = relationship(back_populates="project_accesses")


class Document(Base):
    __tablename__ = "documents"
    # Quota sums filter on exactly this pair (see services/quota_service.py).
    __table_args__ = (Index("ix_documents_project_uploader", "project_id", "uploaded_by_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(150), nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    uploaded_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    project: Mapped["Project"] = relationship(back_populates="documents")


class Image(Base):
    __tablename__ = "images"
    # Quota sums filter on exactly this pair (see services/quota_service.py).
    __table_args__ = (Index("ix_images_project_uploader", "project_id", "uploaded_by_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(150), nullable=False)
    status: Mapped[ImageStatus] = mapped_column(
        SqlEnum(ImageStatus, native_enum=False, length=20),
        nullable=False,
        default=ImageStatus.stored,
    )
    # The original upload's size, fixed at upload time. The original is kept even
    # after a resize, so re-resizing at a different size always works from the
    # full-quality source instead of upscaling an already-shrunk copy.
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    # The current resized copy, or None if the image has never been resized.
    # Both sizes count against quota - see services/quota_service.py.
    resized_size_bytes: Mapped[int | None] = mapped_column(nullable=True)
    original_storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    width: Mapped[int | None] = mapped_column(nullable=True)
    height: Mapped[int | None] = mapped_column(nullable=True)
    uploaded_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    project: Mapped["Project"] = relationship(back_populates="images")
