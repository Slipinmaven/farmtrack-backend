from datetime import date, datetime, time
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Date, DateTime, ForeignKey, Index, Text, Time, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.sale_delivery_items import SaleDeliveryItem
    from app.models.transactions import Transaction


class SaleDelivery(Base):
    __tablename__ = "sale_deliveries"
    __table_args__ = (
        Index("ix_sale_deliveries_transaction_id", "transaction_id"),
        Index("ix_sale_deliveries_delivered_date", "delivered_date"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    transaction_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("transactions.id"), nullable=False
    )
    delivered_date: Mapped[date] = mapped_column(Date, nullable=False)
    delivered_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    transaction: Mapped["Transaction"] = relationship(
        back_populates="sale_deliveries", lazy="raise"
    )
    items: Mapped[list["SaleDeliveryItem"]] = relationship(
        back_populates="sale_delivery",
        lazy="raise",
        cascade="all, delete-orphan",
    )