from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import ImageStatus


class UserCreate(BaseModel):
    login: str = Field(min_length=3, max_length=150)
    password: str = Field(min_length=8, max_length=72)
    repeat_password: str = Field(min_length=8, max_length=72)

    @field_validator("repeat_password")
    @classmethod
    def passwords_match(cls, value: str, info) -> str:
        if info.data.get("password") is not None and value != info.data["password"]:
            raise ValueError("Passwords do not match")
        return value


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    login: str
    created_at: datetime


class LoginRequest(BaseModel):
    login: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class ProjectUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime
    updated_at: datetime


class ImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    filename: str
    content_type: str
    status: ImageStatus
    # The original upload. Stays put after a resize, so both count against quota.
    size_bytes: int
    resized_size_bytes: int | None
    width: int | None
    height: int | None
    created_at: datetime
    updated_at: datetime


class ImageResizeRequest(BaseModel):
    # Bounded so a caller can't ask for dimensions that would exhaust the
    # Lambda's memory. Aspect ratio is preserved, so these are a bounding box:
    # the result fits inside them rather than matching them exactly.
    width: int = Field(default=512, ge=1, le=4096)
    height: int = Field(default=512, ge=1, le=4096)


class ProjectInfo(BaseModel):
    id: int
    name: str
    description: str | None
    owner_id: int
    role: str
    created_at: datetime
    updated_at: datetime


class ProjectFull(ProjectInfo):
    documents: list[DocumentOut] = []
    images: list[ImageOut] = []
