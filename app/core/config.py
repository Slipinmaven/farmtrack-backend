from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "FarmTrack API"
    app_version: str = "1.0.0"
    environment: Literal[
        "development",
        "testing",
        "production",
    ] = "development"
    debug: bool = False
    timezone: str = "Africa/Nairobi"
    media_directory: Path = Path(__file__).resolve().parents[2] / "media"

    # Database
    database_url: str = Field(min_length=1)
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_max_overflow: int = Field(default=5, ge=0, le=50)
    database_pool_timeout: int = Field(default=30, ge=1, le=300)
    database_pool_recycle: int = Field(
        default=1800,
        ge=60,
        le=86400,
    )
    database_pool_pre_ping: bool = True
    database_echo: bool = False

    # Authentication
    jwt_secret_key: str = Field(min_length=32)
    jwt_algorithm: Literal["HS256"] = "HS256"
    jwt_issuer: str = "farmtrack"
    jwt_audience: str = "farmtrack-mobile"
    access_token_expire_minutes: int = Field(
        default=15,
        ge=1,
        le=1440,
    )
    refresh_token_expire_days: int = Field(
        default=30,
        ge=1,
        le=365,
    )

    # Logging
    log_level: str = "INFO"
    log_dir: str = "logs"
    log_max_bytes: int = Field(
        default=10_000_000,
        ge=100_000,
    )
    log_backup_count: int = Field(
        default=5,
        ge=1,
        le=20,
    )
    log_retention_days: int = Field(
        default=30,
        ge=1,
        le=3650,
    )

    # CORS
    cors_origins: list[str] = Field(default_factory=list)

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        normalized = value.upper()
        allowed = {
            "DEBUG",
            "INFO",
            "WARNING",
            "ERROR",
            "CRITICAL",
        }

        if normalized not in allowed:
            raise ValueError(
                f"LOG_LEVEL must be one of {sorted(allowed)}"
            )

        return normalized

    @field_validator("cors_origins", mode="before")
    @classmethod
    def normalize_cors_origins(cls, value: object) -> object:
        if value is None or value == "":
            return []

        if isinstance(value, str):
            return [
                origin.strip()
                for origin in value.split(",")
                if origin.strip()
            ]

        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()