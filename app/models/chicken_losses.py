from datetime import date, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    Integer,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.schemas.enums import ChickenLossReason


class ChickenLoss(Base):
    __tablename__ = "chicken_losses"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_chicken_losses_quantity_positive"),
        Index("ix_chicken_losses_farm_id", "farm_id"),
        Index("ix_chicken_losses_batch_id", "batch_id"),
        Index("ix_chicken_losses_block_id", "block_id"),
        Index("ix_chicken_losses_loss_date", "loss_date"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    farm_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("farms.id"), nullable=False
    )
    batch_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("chicken_batches.id"), nullable=False
    )
    block_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("blocks.id"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    loss_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[ChickenLossReason] = mapped_column(
        SQLEnum(ChickenLossReason, name="chicken_loss_reason"), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )