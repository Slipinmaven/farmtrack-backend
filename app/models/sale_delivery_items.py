from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.sale_deliveries import SaleDelivery
    from app.models.sale_delivery_item_allocations import SaleDeliveryItemAllocation
    from app.models.transaction_items import TransactionItem


class SaleDeliveryItem(Base):
    __tablename__ = "sale_delivery_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_sale_delivery_items_quantity_positive"),
        Index("ix_sale_delivery_items_delivery_id", "sale_delivery_id"),
        Index("ix_sale_delivery_items_transaction_item_id", "transaction_item_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    sale_delivery_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("sale_deliveries.id", ondelete="CASCADE"),
        nullable=False,
    )
    transaction_item_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("transaction_items.id"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    sale_delivery: Mapped["SaleDelivery"] = relationship(
        back_populates="items", lazy="raise"
    )
    transaction_item: Mapped["TransactionItem"] = relationship(lazy="raise")
    batch_allocations: Mapped[list["SaleDeliveryItemAllocation"]] = relationship(
        back_populates="sale_delivery_item",
        lazy="raise",
        cascade="all, delete-orphan",
    )