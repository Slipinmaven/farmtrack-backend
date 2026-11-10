from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AppRelease(Base):
    __tablename__ = "app_releases"
    __table_args__ = (
        CheckConstraint("platform = 'android'", name="check_app_releases_android"),
        CheckConstraint("version_code > 0", name="check_app_releases_version_code"),
        UniqueConstraint(
            "platform",
            "version_code",
            name="uq_app_releases_platform_version_code",
        ),
        UniqueConstraint("github_asset_id", name="uq_app_releases_github_asset_id"),
        CheckConstraint(
            "github_asset_id IS NULL OR github_asset_id > 0",
            name="check_app_releases_github_asset_id",
        ),
        Index(
            "uq_app_releases_latest_platform",
            "platform",
            unique=True,
            postgresql_where=text("is_latest IS TRUE"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    version_code: Mapped[int] = mapped_column(Integer, nullable=False)
    platform: Mapped[str] = mapped_column(
        String(20), nullable=False, default="android", server_default="android"
    )
    github_asset_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    legacy_storage_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    release_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    is_latest: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
