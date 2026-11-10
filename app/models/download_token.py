from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class DownloadToken(Base):
    __tablename__ = "download_tokens"
    __table_args__ = (
        CheckConstraint(
            "delivery_status IN ('pending', 'sent', 'failed', 'prepared')",
            name="check_download_tokens_delivery_status",
        ),
        CheckConstraint(
            "delivery_channel IN ('email', 'whatsapp', 'both')",
            name="check_download_tokens_delivery_channel",
        ),
        Index("ix_download_tokens_expires_at", "expires_at"),
        Index("ix_download_tokens_release_id", "release_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    release_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("app_releases.id", ondelete="CASCADE"),
        nullable=False,
    )
    recipient_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    recipient_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    delivery_channel: Mapped[str] = mapped_column(
        String(20), nullable=False, default="email", server_default="email"
    )
    delivery_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    access_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    release: Mapped["AppRelease"] = relationship(lazy="raise")
