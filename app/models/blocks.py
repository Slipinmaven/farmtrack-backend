from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4
from sqlalchemy import (
    CheckConstraint, 
    DateTime, 
    ForeignKey, 
    String, 
    Integer,
    UniqueConstraint, 
    Text,
    Uuid, 
    func
)

from app.core.database import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from app.models.batch_blocks import BatchBlock
    from app.models.chicken_transaction_items import ChickenTransactionItem
    from app.models.farm import Farm
    from app.models.purchase_receipt_item_block_allocations import (
        PurchaseReceiptItemBlockAllocation,
    )

class Block(Base):
    __tablename__ = "blocks"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    farm_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("farms.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    over_capacity_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "capacity >=0",
            name="block_capacity_non_negative"
        ),
        CheckConstraint(
            "over_capacity_limit >=0",
            name="block_over_capacity_limit_non_negative"
        ),
        UniqueConstraint(
            "farm_id",
            "name",
            name="uq_blocks_farm_id_name"
        )
    )

    farm: Mapped["Farm"] = relationship(
        back_populates="blocks",
        lazy="raise",
    )
    batch_blocks: Mapped[list["BatchBlock"]] = relationship(
        back_populates="block",
        lazy="raise",
        cascade="all, delete-orphan",
    )
    chicken_transaction_items: Mapped[list["ChickenTransactionItem"]] = relationship(
        back_populates="block", lazy="raise"
    )
    purchase_receipt_item_allocations: Mapped[
        list["PurchaseReceiptItemBlockAllocation"]
    ] = relationship(back_populates="block", lazy="raise")