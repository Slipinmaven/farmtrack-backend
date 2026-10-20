from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.blocks import Block
    from app.models.purchase_receipt_items import PurchaseReceiptItem


class PurchaseReceiptItemBlockAllocation(Base):
    __tablename__ = "purchase_receipt_item_block_allocations"
    __table_args__ = (
        CheckConstraint(
            "quantity > 0",
            name="ck_purchase_receipt_item_block_allocations_quantity_positive",
        ),
        UniqueConstraint(
            "purchase_receipt_item_id",
            "block_id",
            name="uq_purchase_receipt_item_block_allocations_item_block",
        ),
        Index(
            "ix_purchase_receipt_item_block_allocations_block_id",
            "block_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    purchase_receipt_item_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("purchase_receipt_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    block_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("blocks.id"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    purchase_receipt_item: Mapped["PurchaseReceiptItem"] = relationship(
        back_populates="block_allocations",
        lazy="raise",
    )
    block: Mapped["Block"] = relationship(lazy="raise")