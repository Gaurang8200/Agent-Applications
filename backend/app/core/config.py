from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, loaded from the repo-root .env."""

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000"

    database_url: str
    redis_url: str = "redis://localhost:6379/0"

    s3_endpoint_url: str | None = None
    s3_access_key: str
    s3_secret_key: str
    s3_bucket: str = "resumes"
    s3_region: str = "us-east-1"

    # Empty until the user creates a key at console.anthropic.com.
    # Ingest falls back to heuristic parsing when this is unset.
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-4-8"

    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def llm_enabled(self) -> bool:
        return bool(self.anthropic_api_key)

    @field_validator("database_url")
    @classmethod
    def _require_psycopg_driver(cls, v: str) -> str:
        if not v.startswith("postgresql+psycopg://"):
            raise ValueError("DATABASE_URL must use the postgresql+psycopg:// driver")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
