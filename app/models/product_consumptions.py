from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ProductConsumption(Base):
    __tablename__ = "product_consumptions"
    __table_args__ = (
        CheckConstraint(
            "quantity > 0",
            name="ck_product_consumptions_quantity_positive",
        ),
        CheckConstraint(
            "conversion_factor > 0",
            name="ck_product_consumptions_conversion_factor_positive",
        ),
        Index("ix_product_consumptions_farm_id", "farm_id"),
        Index("ix_product_consumptions_product_id", "product_id"),
        Index("ix_product_consumptions_unit_id", "unit_id"),
        Index("ix_product_consumptions_block_id", "block_id"),
        Index("ix_product_consumptions_batch_id", "batch_id"),
        Index("ix_product_consumptions_consumption_date", "consumption_date"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    farm_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("farms.id"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("products.id"), nullable=False
    )
    unit_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("units.id"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    conversion_factor: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    block_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("blocks.id"), nullable=True
    )
    batch_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("chicken_batches.id"), nullable=True
    )
    consumption_date: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )