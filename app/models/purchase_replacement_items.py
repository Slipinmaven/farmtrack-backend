from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.chicken_batches import ChickenBatch
    from app.models.purchase_replacement_item_allocations import PurchaseReplacementItemAllocation
    from app.models.purchase_replacements import PurchaseReplacement
    from app.models.purchase_return_items import PurchaseReturnItem


class PurchaseReplacementItem(Base):
    __tablename__ = "purchase_replacement_items"
    __table_args__ = (
        CheckConstraint(
            "quantity_received > 0",
            name="ck_purchase_replacement_items_quantity_positive",
        ),
        CheckConstraint(
            "bonus_quantity >= 0 AND bonus_quantity <= quantity_received",
            name="ck_purchase_replacement_items_bonus_quantity_valid",
        ),
        CheckConstraint(
            "credit_applied_amount >= 0",
            name="ck_purchase_replacement_items_credit_non_negative",
        ),
        Index("ix_purchase_replacement_items_purchase_return_item_id", "purchase_return_item_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    purchase_replacement_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("purchase_replacements.id", ondelete="CASCADE"),
        nullable=False,
    )
    purchase_return_item_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("purchase_return_items.id"), nullable=False
    )
    batch_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("chicken_batches.id"), nullable=False
    )
    quantity_received: Mapped[int] = mapped_column(Integer, nullable=False)
    bonus_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    credit_applied_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    purchase_replacement: Mapped["PurchaseReplacement"] = relationship(
        back_populates="items", lazy="raise"
    )
    purchase_return_item: Mapped["PurchaseReturnItem"] = relationship(lazy="raise")
    batch: Mapped["ChickenBatch"] = relationship(lazy="raise")
    block_allocations: Mapped[list["PurchaseReplacementItemAllocation"]] = relationship(
        back_populates="purchase_replacement_item",
        lazy="raise",
        cascade="all, delete-orphan",
    )