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
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.products import Product
    from app.models.units import Unit


class ProductUnit(Base):
    __tablename__ = "product_units"
    __table_args__ = (
        CheckConstraint(
            "conversion_factor > 0 AND "
            "(is_base_unit = false OR conversion_factor = 1)",
            name="ck_product_units_conversion_factor",
        ),
        UniqueConstraint(
            "product_id",
            "unit_id",
            name="uq_product_units_product_id_unit_id",
        ),
        Index("ix_product_units_product_id", "product_id"),
        Index("ix_product_units_unit_id", "unit_id"),
        Index(
            "uq_product_units_one_base_unit",
            "product_id",
            unique=True,
            postgresql_where=text("is_base_unit = true"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    product_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("products.id"), nullable=False
    )
    unit_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("units.id"), nullable=False
    )
    conversion_factor: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    is_base_unit: Mapped[bool] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    product: Mapped["Product"] = relationship(
        back_populates="product_units",
        lazy="raise",
    )
    unit: Mapped["Unit"] = relationship(
        back_populates="product_units",
        lazy="raise",
    )