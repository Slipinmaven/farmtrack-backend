from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum as SQLEnum, ForeignKey, Index, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.schemas.enums import ActivityEntityType, ActivityType

if TYPE_CHECKING:
    from app.models.farm import Farm
    from app.models.user import User
    from app.models.user_session import UserSession


class Activity(Base):
    __tablename__ = "activities"
    __table_args__ = (
        Index(
            "ix_activities_farm_id_created_at_id",
            "farm_id",
            "created_at",
            "id",
        ),
        Index(
            "ix_activities_entity_type_entity_id",
            "entity_type",
            "entity_id",
        ),
        Index("ix_activities_session_id", "session_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    farm_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("farms.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    session_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("user_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    type: Mapped[ActivityType] = mapped_column(
        SQLEnum(ActivityType, name="activitytype"), nullable=False
    )
    entity_type: Mapped[ActivityEntityType] = mapped_column(
        SQLEnum(ActivityEntityType, name="activityentitytype"), nullable=False
    )
    entity_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    details: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    farm: Mapped["Farm"] = relationship(
        back_populates="activities",
        lazy="raise",
    )
    user: Mapped["User | None"] = relationship(
        back_populates="activities",
        lazy="raise",
        passive_deletes=True,
    )
    session: Mapped["UserSession | None"] = relationship(
        back_populates="activities",
        lazy="raise",
    )