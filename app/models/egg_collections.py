from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EggCollection(Base):
    __tablename__ = "egg_collections"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_egg_collections_quantity_positive"),
        CheckConstraint(
            "conversion_factor > 0",
            name="ck_egg_collections_conversion_factor_positive",
        ),
        Index("ix_egg_collections_farm_id", "farm_id"),
        Index("ix_egg_collections_product_id", "product_id"),
        Index("ix_egg_collections_block_id", "block_id"),
        Index("ix_egg_collections_unit_id", "unit_id"),
        Index("ix_egg_collections_collected_at", "collected_at"),
        CheckConstraint(
            "entry_type IN ('collection', 'opening_stock')",
            name="ck_egg_collections_entry_type",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    farm_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("farms.id"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("products.id"), nullable=False
    )
    block_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("blocks.id"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    unit_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("units.id"), nullable=False
    )
    conversion_factor: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    entry_type: Mapped[str] = mapped_column(
        String(24), nullable=False, default="collection", server_default="collection"
    )
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )