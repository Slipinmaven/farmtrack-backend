from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Uuid, func, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.user import User

class AppSecuritySettings(Base):
    __tablename__ = "app_security_settings"

    __table_args__= (
        CheckConstraint("auto_lock_minutes >=0", name="check_auto_lock_minutes_non_negative"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False, unique=True)
    biometric_unlock_enable: Mapped[bool] = mapped_column(nullable=False, default=False)
    passcode_enabled: Mapped[bool] = mapped_column(nullable=False, default=False)
    auto_lock_enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    auto_lock_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=5)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(
        back_populates="app_security_setting",
        lazy="raise"
    )