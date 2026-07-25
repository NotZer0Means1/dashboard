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

    # The resize Lambda, invoked synchronously by POST /image/{id}/resize.
    resize_lambda_name: str = "dashboard-resize-image"
    # Upper bound on requested dimensions. Without it a caller could ask for
    # 50000x50000 and blow the Lambda's memory (and the project's quota).
    max_resize_dimension: int = 4096
    default_resize_dimension: int = 512


@lru_cache
def get_settings() -> Settings:
    return Settings()
