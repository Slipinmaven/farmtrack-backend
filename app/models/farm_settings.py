from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4
from sqlalchemy import (
    DateTime, 
    Enum as SQLEnum,
    ForeignKey, 
    Uuid, 
    String,
    Text,
    Numeric,
    func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.schemas.enums import ThemeMode

if TYPE_CHECKING:
    from app.models.farm import Farm

class FarmSettings(Base):
    __tablename__ = "farm_settings"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    farm_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("farms.id"), nullable=False, unique=True)
    primary_color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    secondary_color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    font_family: Mapped[str | None] = mapped_column(String(50), nullable=True)
    font_scale: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    theme_mode: Mapped[ThemeMode] = mapped_column(
        SQLEnum(
            ThemeMode,
            name="thememode",
            values_callable=lambda enum_type: [member.value for member in enum_type],
        ),
        nullable=False,
        default=ThemeMode.SYSTEM,
        server_default=ThemeMode.SYSTEM.value,
    )
    logo_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    farm: Mapped["Farm"] = relationship(
        back_populates="farm_settings",
        lazy="raise"
    )