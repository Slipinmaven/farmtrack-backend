from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.blocks import Block
    from app.models.chicken_batches import ChickenBatch
    from app.models.transaction_items import TransactionItem


class ChickenTransactionItem(Base):
    __tablename__ = "chicken_transaction_items"
    __table_args__ = (
        Index("ix_chicken_transaction_items_batch_id", "batch_id"),
        Index("ix_chicken_transaction_items_block_id", "block_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    transaction_item_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("transaction_items.id"),
        nullable=False,
        unique=True,
    )
    batch_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("chicken_batches.id"), nullable=False
    )
    block_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("blocks.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    transaction_item: Mapped["TransactionItem"] = relationship(
        back_populates="chicken_transaction_item", lazy="raise"
    )
    batch: Mapped["ChickenBatch"] = relationship(
        back_populates="chicken_transaction_items", lazy="raise"
    )
    block: Mapped["Block | None"] = relationship(
        back_populates="chicken_transaction_items", lazy="raise"
    )
