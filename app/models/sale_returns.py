from datetime import date, datetime, time
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    Time,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.sale_return_items import SaleReturnItem
    from app.models.transactions import Transaction


class SaleReturn(Base):
    __tablename__ = "sale_returns"
    __table_args__ = (
        CheckConstraint(
            "return_type IN ('undelivered_cancelled', 'delivered_return')",
            name="ck_sale_returns_type_valid",
        ),
        Index("ix_sale_returns_transaction_id", "transaction_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    transaction_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("transactions.id"), nullable=False
    )
    return_type: Mapped[str] = mapped_column(String(32), nullable=False)
    return_date: Mapped[date] = mapped_column(Date, nullable=False)
    return_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    transaction: Mapped["Transaction"] = relationship(
        back_populates="sale_returns", lazy="raise"
    )
    items: Mapped[list["SaleReturnItem"]] = relationship(
        back_populates="sale_return",
        lazy="raise",
        cascade="all, delete-orphan",
    )