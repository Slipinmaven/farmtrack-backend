from datetime import date, datetime
from decimal import Decimal
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
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.schemas.enums import PaymentMethod


class ExpensePayment(Base):
    __tablename__ = "expense_payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_expense_payments_amount_positive"),
        CheckConstraint(
            "kind IN ('payment', 'refund')",
            name="ck_expense_payments_kind_valid",
        ),
        Index("ix_expense_payments_expense_id", "expense_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    expense_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("expenses.id", ondelete="CASCADE"), nullable=False
    )
    purchase_payment_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("transaction_payments.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="payment")
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    payment_method: Mapped[PaymentMethod] = mapped_column(
        SQLEnum(PaymentMethod, name="paymentmethod"), nullable=False
    )
    reference_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expense: Mapped["Expense"] = relationship(back_populates="payments")
