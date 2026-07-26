from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/dashboard"
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    aws_region: str = "us-east-1"
    aws_s3_bucket: str = "dashboard-documents"

    max_user_upload_bytes_per_project: int = 10 * 1024 * 1024

    # Shared secret the resize Lambda must present when reporting a result back.
    # The dimensions themselves live on the function (MAX_IMAGE_DIMENSION), not
    # here - the app never tells it what size to produce.
    internal_callback_token: str = "change-me-internal-token"


@lru_cache
def get_settings() -> Settings:
    return Settings()
