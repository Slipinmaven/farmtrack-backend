import re
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
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

    # Email
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from_email: str | None = None
    farmtrack_app_url: str = "farmtrack://farm-team"
    app_release_admin_emails: list[str] = Field(default_factory=list)
    github_release_repository: str | None = None
    github_release_token: SecretStr | None = None
    app_public_base_url: str | None = None
    download_token_expiry_days: int = Field(default=7, ge=1, le=30)

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

    @field_validator("app_release_admin_emails", mode="before")
    @classmethod
    def normalize_app_release_admin_emails(cls, value: object) -> object:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [email.strip().lower() for email in value.split(",") if email.strip()]
        if isinstance(value, list):
            return [
                str(email).strip().lower()
                for email in value
                if str(email).strip()
            ]
        return value

    @field_validator("github_release_repository", "app_public_base_url")
    @classmethod
    def normalize_optional_settings(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.strip()
        return normalized.rstrip("/") if normalized.startswith(("http://", "https://")) else normalized

    @field_validator("github_release_repository")
    @classmethod
    def validate_github_release_repository(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if (
            re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value) is None
            or value.rsplit("/", maxsplit=1)[-1].lower().endswith(".git")
        ):
            raise ValueError(
                "GITHUB_RELEASE_REPOSITORY must be in owner/repository format."
            )
        return value

    @field_validator("github_release_token", mode="before")
    @classmethod
    def normalize_github_release_token(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("app_public_base_url")
    @classmethod
    def validate_service_urls(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("Service URL settings must be an HTTP(S) origin.")
        if parsed.scheme != "https" and parsed.hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            raise ValueError("Service URLs must use HTTPS outside localhost.")
        return value

    @field_validator("smtp_username", "smtp_from_email")
    @classmethod
    def normalize_smtp_email_address(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.strip()
        if not normalized or "\r" in normalized or "\n" in normalized:
            raise ValueError("SMTP email addresses must not contain line breaks.")
        return normalized

    @field_validator("smtp_password", mode="before")
    @classmethod
    def normalize_smtp_password(cls, value: object) -> object:
        return None if value == "" else value

    @model_validator(mode="after")
    def validate_smtp_configuration(self) -> "Settings":
        if (self.smtp_username is None) != (self.smtp_password is None):
            raise ValueError(
                "SMTP_USERNAME and SMTP_PASSWORD must be configured together."
            )
        if self.smtp_from_email is not None and self.smtp_username is None:
            raise ValueError(
                "SMTP_USERNAME and SMTP_PASSWORD are required when SMTP_FROM_EMAIL is set."
            )
        if (self.github_release_repository is None) != (
            self.github_release_token is None
        ):
            raise ValueError(
                "GITHUB_RELEASE_REPOSITORY and GITHUB_RELEASE_TOKEN must be "
                "configured together."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()