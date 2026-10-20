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
    from app.models.chicken_batches import ChickenBatch
    from app.models.purchase_return_items import PurchaseReturnItem


class PurchaseReturnItemAllocation(Base):
    __tablename__ = "purchase_return_item_allocations"
    __table_args__ = (
        CheckConstraint(
            "quantity > 0",
            name="ck_purchase_return_item_allocations_quantity_positive",
        ),
        UniqueConstraint(
            "purchase_return_item_id",
            "block_id",
            name="uq_purchase_return_item_allocations_item_block",
        ),
        Index("ix_purchase_return_item_allocations_batch_id", "batch_id"),
        Index("ix_purchase_return_item_allocations_block_id", "block_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    purchase_return_item_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("purchase_return_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    batch_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("chicken_batches.id"), nullable=False
    )
    block_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("blocks.id"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    purchase_return_item: Mapped["PurchaseReturnItem"] = relationship(
        back_populates="block_allocations", lazy="raise"
    )
    batch: Mapped["ChickenBatch"] = relationship(lazy="raise")
    block: Mapped["Block"] = relationship(lazy="raise")