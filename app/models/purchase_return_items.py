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
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.purchase_return_item_allocations import PurchaseReturnItemAllocation
    from app.models.purchase_returns import PurchaseReturn
    from app.models.transaction_items import TransactionItem


class PurchaseReturnItem(Base):
    __tablename__ = "purchase_return_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_purchase_return_items_quantity_positive"),
        CheckConstraint(
            "credit_amount >= 0",
            name="ck_purchase_return_items_credit_non_negative",
        ),
        UniqueConstraint(
            "purchase_return_id",
            "transaction_item_id",
            name="uq_purchase_return_items_return_transaction_item",
        ),
        Index("ix_purchase_return_items_return_id", "purchase_return_id"),
        Index("ix_purchase_return_items_transaction_item_id", "transaction_item_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    purchase_return_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("purchase_returns.id", ondelete="CASCADE"),
        nullable=False,
    )
    transaction_item_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("transaction_items.id"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    credit_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    purchase_return: Mapped["PurchaseReturn"] = relationship(
        back_populates="items", lazy="raise"
    )
    transaction_item: Mapped["TransactionItem"] = relationship(lazy="raise")
    block_allocations: Mapped[list["PurchaseReturnItemAllocation"]] = relationship(
        back_populates="purchase_return_item",
        lazy="raise",
        cascade="all, delete-orphan",
    )