from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.schemas.enums import UserRole

if TYPE_CHECKING:
    from app.models.app_security_settings import AppSecuritySettings
    from app.models.activities import Activity
    from app.models.farm import Farm
    from app.models.farm_membership import FarmMembership
    from app.models.refresh_token import RefreshToken

class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('USER', 'SUPER_ADMIN')",
            name="ck_users_role",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=UserRole.USER.value,
        server_default=UserRole.USER.value,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deletion_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    deletion_confirmation_token_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )
    deletion_confirmation_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="raise",
    )
    farms: Mapped[list["Farm"]] = relationship(
        back_populates="owner",
        lazy="raise",
        cascade="all, delete-orphan",
    )
    app_security_setting: Mapped["AppSecuritySettings"] = relationship(
        back_populates="user",
        lazy="raise",
        cascade="all, delete-orphan",
    )
    activities: Mapped[list["Activity"]] = relationship(
        back_populates="user",
        lazy="raise",
        passive_deletes=True,
    )
    farm_memberships: Mapped[list["FarmMembership"]] = relationship(
        back_populates="user",
        foreign_keys="FarmMembership.user_id",
        lazy="raise",
        passive_deletes=True,
    )
