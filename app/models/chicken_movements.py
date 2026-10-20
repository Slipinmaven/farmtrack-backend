from datetime import date, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ChickenMovement(Base):
    __tablename__ = "chicken_movements"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_chicken_movements_quantity_positive"),
        CheckConstraint(
            "from_block_id <> to_block_id",
            name="ck_chicken_movements_blocks_different",
        ),
        Index("ix_chicken_movements_farm_id", "farm_id"),
        Index("ix_chicken_movements_batch_id", "batch_id"),
        Index("ix_chicken_movements_from_block_id", "from_block_id"),
        Index("ix_chicken_movements_to_block_id", "to_block_id"),
        Index("ix_chicken_movements_movement_date", "movement_date"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    farm_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("farms.id"), nullable=False
    )
    batch_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("chicken_batches.id"), nullable=False
    )
    from_block_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("blocks.id"), nullable=False
    )
    to_block_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("blocks.id"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    movement_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )