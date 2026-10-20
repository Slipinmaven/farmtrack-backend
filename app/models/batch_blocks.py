from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4
from sqlalchemy import (
    CheckConstraint, 
    DateTime, 
    ForeignKey, 
    Integer,
    UniqueConstraint, 
    Uuid, 
    func
)

from app.core.database import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from app.models.blocks import Block
    from app.models.chicken_batches import ChickenBatch

class BatchBlock(Base):
    __tablename__ = "batch_blocks"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    block_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("blocks.id"), nullable=False
    )
    batch_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("chicken_batches.id"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "quantity >= 0",
            name="batch_block_non_negative"
        ),
        UniqueConstraint(
            "block_id",
            "batch_id",
            name="uq_batch_blocks_block_id_batch_id",
        ),
    )

    block: Mapped["Block"] = relationship(
        back_populates="batch_blocks",
        lazy="raise",
    )
    batch: Mapped["ChickenBatch"] = relationship(
        back_populates="batch_blocks",
        lazy="raise",
    )

    