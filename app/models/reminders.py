from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.schemas.enums import ReminderStatus

if TYPE_CHECKING:
    from app.models.farm import Farm


class Reminder(Base):
    __tablename__ = "reminders"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'COMPLETED', 'CANCELLED')",
            name="ck_reminders_status",
        ),
        CheckConstraint(
            "delivery_channel IN ('in_app', 'push') AND "
            "(delivery_channel != 'push' OR expo_push_token IS NOT NULL)",
            name="ck_reminders_delivery_channel",
        ),
        Index("ix_reminders_farm_id_due_at", "farm_id", "due_at"),
            Index(
                "ix_reminders_pending_due_at",
                "due_at",
                postgresql_where=text(
                    "status = 'PENDING' AND notification_enqueued_at IS NULL"
                ),
            ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    farm_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("farms.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    delivery_channel: Mapped[str] = mapped_column(
        String(10), nullable=False, default="in_app", server_default="in_app"
    )
    expo_push_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ReminderStatus.PENDING.value
    )
    recurrence_rule: Mapped[dict[str, object] | None] = mapped_column(
        JSONB, nullable=True
    )
    related_entity_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    related_entity_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notification_enqueued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )