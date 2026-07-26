from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


class InviteOut(BaseModel):
    message: str


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


class ImageResizeCallback(BaseModel):
    # Body the resize Lambda POSTs to /internal/... once it has finished with an
    # object. resized_size_bytes is required unless failed=true, which the Lambda
    # sends when it could not decode the original at all.
    resized_size_bytes: int | None = Field(default=None, gt=0)
    width: int | None = None
    height: int | None = None
    failed: bool = False
    error: str | None = None

    @model_validator(mode="after")
    def _require_size_unless_failed(self) -> "ImageResizeCallback":
        if not self.failed and self.resized_size_bytes is None:
            raise ValueError("resized_size_bytes is required when failed=false")
        return self


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
