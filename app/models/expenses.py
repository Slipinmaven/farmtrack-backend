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
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.schemas.enums import PaymentMethod
from app.models.blocks import Block
from app.models.contact import Contact
from app.models.expense_payment import ExpensePayment
from app.models.transactions import Transaction

class Expense(Base):
    __tablename__ = "expenses"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_expenses_amount_positive"),
        Index("ix_expenses_farm_id", "farm_id"),
        Index("ix_expenses_category", "category"),
        Index("ix_expenses_expense_date", "expense_date"),
        Index("ix_expenses_contact_id", "contact_id"),
        Index("ix_expenses_block_id", "block_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    farm_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("farms.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    expense_date: Mapped[date] = mapped_column(Date, nullable=False)
    contact_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("contacts.id"), nullable=True
    )
    block_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("blocks.id"), nullable=True
    )
    purchase_transaction_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("transactions.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
    )
    receipt_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    payment_method: Mapped[PaymentMethod] = mapped_column(
        SQLEnum(PaymentMethod, name="paymentmethod"), nullable=False
    )
    reference_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    canceled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    payments: Mapped[list["ExpensePayment"]] = relationship(
        back_populates="expense",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ExpensePayment.payment_date, ExpensePayment.created_at",
    )
    contact: Mapped["Contact | None"] = relationship(lazy="joined")
    block: Mapped["Block | None"] = relationship(lazy="joined")
    purchase_transaction: Mapped["Transaction | None"] = relationship(
        lazy="joined",
        foreign_keys=[purchase_transaction_id],
    )