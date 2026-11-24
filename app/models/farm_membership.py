from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.farm import Farm
    from app.models.user import User


class FarmMembership(Base):
    __tablename__ = "farm_memberships"
    __table_args__ = (
        UniqueConstraint("farm_id", "user_id", name="uq_farm_memberships_farm_user"),
        CheckConstraint(
            "role IN ('owner', 'manager', 'worker')",
            name="check_farm_memberships_role",
        ),
        CheckConstraint(
            "status IN ('invited', 'active', 'revoked')",
            name="check_farm_memberships_status",
        ),
        CheckConstraint(
            "invitation_email_status IN "
            "('not_configured', 'queued', 'sent', 'failed', 'cancelled')",
            name="check_farm_memberships_invitation_email_status",
        ),
        Index("ix_farm_memberships_user_status", "user_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    farm_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("farms.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="invited",
        server_default="invited",
    )
    invited_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    invited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    account_deletion_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    account_deletion_previous_status: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )
    invitation_email_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="not_configured",
        server_default="not_configured",
    )
    invitation_email_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    farm: Mapped["Farm"] = relationship(back_populates="memberships", lazy="raise")
    user: Mapped["User"] = relationship(
        back_populates="farm_memberships",
        foreign_keys=[user_id],
        lazy="raise",
    )
    invited_by: Mapped["User | None"] = relationship(
        foreign_keys=[invited_by_id],
        lazy="raise",
    )
