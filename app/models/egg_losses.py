from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    Numeric,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.schemas.enums import EggLossReason


class EggLoss(Base):
    __tablename__ = "egg_losses"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_egg_losses_quantity_positive"),
        CheckConstraint(
            "conversion_factor > 0",
            name="ck_egg_losses_conversion_factor_positive",
        ),
        Index("ix_egg_losses_farm_id", "farm_id"),
        Index("ix_egg_losses_product_id", "product_id"),
        Index("ix_egg_losses_unit_id", "unit_id"),
        Index("ix_egg_losses_loss_date", "loss_date"),
        Index("ix_egg_losses_reason", "reason"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    farm_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("farms.id"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("products.id"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    unit_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("units.id"), nullable=False
    )
    conversion_factor: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    loss_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[EggLossReason] = mapped_column(
        SQLEnum(EggLossReason, name="egg_loss_reason"), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )