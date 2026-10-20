from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.product_units import ProductUnit
    from app.models.transaction_items import TransactionItem


class Unit(Base):
    __tablename__ = "units"
    __table_args__ = (
        UniqueConstraint("name", name="uq_units_name"),
        UniqueConstraint("abbreviation", name="uq_units_abbreviation"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    abbreviation: Mapped[str] = mapped_column(String(10), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    product_units: Mapped[list["ProductUnit"]] = relationship(
        back_populates="unit",
        lazy="raise",
        passive_deletes="all",
    )
    transaction_items: Mapped[list["TransactionItem"]] = relationship(
        back_populates="unit", lazy="raise"
    )