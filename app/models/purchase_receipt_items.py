from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.purchase_receipt_item_block_allocations import (
        PurchaseReceiptItemBlockAllocation,
    )
    from app.models.purchase_receipts import PurchaseReceipt
    from app.models.transaction_items import TransactionItem


class PurchaseReceiptItem(Base):
    __tablename__ = "purchase_receipt_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_purchase_receipt_items_quantity_positive"),
        Index("ix_purchase_receipt_items_receipt_id", "purchase_receipt_id"),
        Index("ix_purchase_receipt_items_transaction_item_id", "transaction_item_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    purchase_receipt_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("purchase_receipts.id"), nullable=False
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

    purchase_receipt: Mapped["PurchaseReceipt"] = relationship(
        back_populates="items", lazy="raise"
    )
    block_allocations: Mapped[list["PurchaseReceiptItemBlockAllocation"]] = relationship(
        back_populates="purchase_receipt_item",
        lazy="raise",
        cascade="all, delete-orphan",
    )
    transaction_item: Mapped["TransactionItem"] = relationship(
        back_populates="purchase_receipt_items", lazy="raise"
    )
