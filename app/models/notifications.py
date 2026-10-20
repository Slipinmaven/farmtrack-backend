from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    String,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.schemas.enums import NotificationCategory, NotificationPriority


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index(
            "ix_notifications_recipient_farm_created",
            "recipient_user_id",
            "farm_id",
            "created_at",
            "id",
        ),
        Index(
            "ix_notifications_unread_recipient_farm_created",
            "recipient_user_id",
            "farm_id",
            "created_at",
            postgresql_where=text("read_at IS NULL AND archived_at IS NULL"),
        ),
        Index(
            "ix_notifications_active_recipient_farm_created",
            "recipient_user_id",
            "farm_id",
            "created_at",
            postgresql_where=text("archived_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    farm_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("farms.id", ondelete="CASCADE"), nullable=False
    )
    recipient_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    source_event_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("notification_outbox.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[NotificationCategory] = mapped_column(
        SQLEnum(
            NotificationCategory,
            name="notificationcategory",
            values_callable=lambda enum_type: [
                member.value for member in enum_type
            ],
        ),
        nullable=False,
    )
    priority: Mapped[NotificationPriority] = mapped_column(
        SQLEnum(
            NotificationPriority,
            name="notificationpriority",
            values_callable=lambda enum_type: [
                member.value for member in enum_type
            ],
        ),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    entity_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )