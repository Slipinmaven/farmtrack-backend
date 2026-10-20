from datetime import date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    Time,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.schemas.enums import PaymentMethod

if TYPE_CHECKING:
    from app.models.purchase_return_items import PurchaseReturnItem
    from app.models.transactions import Transaction


class PurchaseSupplierRefund(Base):
    __tablename__ = "purchase_supplier_refunds"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_purchase_supplier_refunds_amount_positive"),
        Index("ix_purchase_supplier_refunds_transaction_id", "transaction_id"),
        Index("ix_purchase_supplier_refunds_return_item_id", "purchase_return_item_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    transaction_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("transactions.id"), nullable=False
    )
    purchase_return_item_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("purchase_return_items.id"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    refund_date: Mapped[date] = mapped_column(Date, nullable=False)
    refund_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    payment_method: Mapped[PaymentMethod] = mapped_column(
        SQLEnum(PaymentMethod, name="paymentmethod"), nullable=False
    )
    reference_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    transaction: Mapped["Transaction"] = relationship(
        back_populates="purchase_supplier_refunds", lazy="raise"
    )
    purchase_return_item: Mapped["PurchaseReturnItem"] = relationship(lazy="raise")