from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.app_security_settings import AppSecuritySettings
    from app.models.activities import Activity
    from app.models.farm import Farm
    from app.models.farm_membership import FarmMembership
    from app.models.refresh_token import RefreshToken

class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
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
