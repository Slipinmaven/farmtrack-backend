from datetime import date, datetime, time
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Date, DateTime, ForeignKey, Index, Text, Time, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.purchase_replacement_items import PurchaseReplacementItem
    from app.models.purchase_returns import PurchaseReturn
    from app.models.transactions import Transaction


class PurchaseReplacement(Base):
    __tablename__ = "purchase_replacements"
    __table_args__ = (
        Index("ix_purchase_replacements_transaction_id", "transaction_id"),
        Index("ix_purchase_replacements_purchase_return_id", "purchase_return_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    transaction_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("transactions.id"), nullable=False
    )
    purchase_return_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("purchase_returns.id"), nullable=False
    )
    replacement_date: Mapped[date] = mapped_column(Date, nullable=False)
    replacement_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    transaction: Mapped["Transaction"] = relationship(
        back_populates="purchase_replacements", lazy="raise"
    )
    purchase_return: Mapped["PurchaseReturn"] = relationship(
        back_populates="replacements", lazy="raise"
    )
    items: Mapped[list["PurchaseReplacementItem"]] = relationship(
        back_populates="purchase_replacement",
        lazy="raise",
        cascade="all, delete-orphan",
    )