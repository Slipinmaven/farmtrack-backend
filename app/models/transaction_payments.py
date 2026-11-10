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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.schemas.enums import PaymentMethod

if TYPE_CHECKING:
    from app.models.transactions import Transaction


class TransactionPayment(Base):
    __tablename__ = "transaction_payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_transaction_payments_amount_positive"),
        Index("ix_transaction_payments_transaction_id", "transaction_id"),
        Index("ix_transaction_payments_payment_date", "payment_date"),
        Index(
            "uq_transaction_payments_mpesa_reference",
            text("lower(trim(reference_number))"),
            unique=True,
            postgresql_where=text(
                "payment_method = 'MPESA' AND reference_number IS NOT NULL "
                "AND btrim(reference_number) <> ''"
            ),
            sqlite_where=text(
                "payment_method = 'MPESA' AND reference_number IS NOT NULL "
                "AND trim(reference_number) <> ''"
            ),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    transaction_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("transactions.id"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    payment_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    payment_method: Mapped[PaymentMethod] = mapped_column(
        SQLEnum(PaymentMethod, name="paymentmethod"), nullable=False
    )
    reference_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    transaction: Mapped["Transaction"] = relationship(
        back_populates="payments", lazy="raise"
    )