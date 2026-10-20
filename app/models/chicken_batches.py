from datetime import datetime, date
from typing import TYPE_CHECKING
from uuid import UUID, uuid4
from sqlalchemy import (
    DateTime,
    Date,
    Boolean,
    ForeignKey, 
    String, 
    Text,
    Enum as SQLEnum,
    UniqueConstraint, 
    Uuid, 
    func
)

from app.core.database import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.schemas.enums import ChickenType, ChickenBatchStatus

if TYPE_CHECKING:
    from app.models.batch_blocks import BatchBlock
    from app.models.chicken_transaction_items import ChickenTransactionItem
    from app.models.farm import Farm

class ChickenBatch(Base):
    __tablename__ = "chicken_batches"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    farm_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("farms.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    chicken_type: Mapped[ChickenType] = mapped_column(SQLEnum(ChickenType), nullable=False, default=ChickenType.LAYERS)
    breed: Mapped[str | None] = mapped_column(String(100), nullable=True)
    hatch_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[ChickenBatchStatus] = mapped_column(SQLEnum(ChickenBatchStatus), nullable=False, default=ChickenBatchStatus.ACTIVE)
    is_opening_stock: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("farm_id", "name", name="uq_chicken_batches_farm_id_name"),
    )

    farm: Mapped["Farm"] = relationship(
        back_populates="chicken_batches",
        lazy="raise",
    )
    batch_blocks: Mapped[list["BatchBlock"]] = relationship(
        back_populates="batch",
        lazy="raise",
        cascade="all, delete-orphan",
    )
    chicken_transaction_items: Mapped[list["ChickenTransactionItem"]] = relationship(
        back_populates="batch", lazy="raise"
    )
        