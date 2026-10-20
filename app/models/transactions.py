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
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.schemas.enums import TransactionStatus, TransactionType

if TYPE_CHECKING:
    from app.models.contact import Contact
    from app.models.farm import Farm
    from app.models.purchase_receipts import PurchaseReceipt
    from app.models.purchase_returns import PurchaseReturn
    from app.models.purchase_replacements import PurchaseReplacement
    from app.models.purchase_supplier_refunds import PurchaseSupplierRefund
    from app.models.sale_deliveries import SaleDelivery
    from app.models.sale_returns import SaleReturn
    from app.models.transaction_payments import TransactionPayment
    from app.models.transaction_refunds import TransactionRefund
    from app.models.transaction_settlements import TransactionSettlement
    from app.models.transaction_items import TransactionItem


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint(
            "discount_value >= 0",
            name="ck_transactions_discount_value_non_negative",
        ),
        CheckConstraint(
            "discount_amount >= 0",
            name="ck_transactions_discount_amount_non_negative",
        ),
        CheckConstraint(
            "discount_type IS NULL OR discount_type IN ('fixed', 'percentage')",
            name="ck_transactions_discount_type_valid",
        ),
        CheckConstraint(
            "discount_type != 'percentage' OR discount_value <= 100",
            name="ck_transactions_percentage_discount_maximum",
        ),
        CheckConstraint(
            "discount_type IS NOT NULL OR discount_value = 0",
            name="ck_transactions_discount_terms_consistent",
        ),
        UniqueConstraint(
            "farm_id",
            "reference_number",
            name="uq_transactions_farm_reference_number",
        ),
        Index("ix_transactions_farm_id", "farm_id"),
        Index("ix_transactions_contact_id", "contact_id"),
        Index("ix_transactions_transaction_type", "transaction_type"),
        Index("ix_transactions_status", "status"),
        Index("ix_transactions_transaction_date", "transaction_date"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    farm_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("farms.id"), nullable=False
    )
    contact_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True
    )
    transaction_type: Mapped[TransactionType] = mapped_column(
        SQLEnum(TransactionType, name="transactiontype"), nullable=False
    )
    status: Mapped[TransactionStatus] = mapped_column(
        SQLEnum(TransactionStatus, name="transactionstatus"), nullable=False
    )
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    transaction_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    reference_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    discount_type: Mapped[str | None] = mapped_column(String(12), nullable=True)
    discount_value: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    discount_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    farm: Mapped["Farm"] = relationship(back_populates="transactions", lazy="raise")
    contact: Mapped["Contact | None"] = relationship(
        back_populates="transactions", lazy="raise"
    )
    items: Mapped[list["TransactionItem"]] = relationship(
        back_populates="transaction", lazy="raise", cascade="all, delete-orphan"
    )
    purchase_receipts: Mapped[list["PurchaseReceipt"]] = relationship(
        back_populates="transaction", lazy="raise", cascade="all, delete-orphan"
    )
    purchase_returns: Mapped[list["PurchaseReturn"]] = relationship(
        back_populates="transaction", lazy="raise", cascade="all, delete-orphan"
    )
    purchase_replacements: Mapped[list["PurchaseReplacement"]] = relationship(
        back_populates="transaction", lazy="raise", cascade="all, delete-orphan"
    )
    purchase_supplier_refunds: Mapped[list["PurchaseSupplierRefund"]] = relationship(
        back_populates="transaction", lazy="raise", cascade="all, delete-orphan"
    )
    sale_deliveries: Mapped[list["SaleDelivery"]] = relationship(
        back_populates="transaction", lazy="raise", cascade="all, delete-orphan"
    )
    sale_returns: Mapped[list["SaleReturn"]] = relationship(
        back_populates="transaction", lazy="raise", cascade="all, delete-orphan"
    )
    payments: Mapped[list["TransactionPayment"]] = relationship(
        back_populates="transaction", lazy="raise", cascade="all, delete-orphan"
    )
    refunds: Mapped[list["TransactionRefund"]] = relationship(
        back_populates="transaction", lazy="raise", cascade="all, delete-orphan"
    )
    settlements: Mapped[list["TransactionSettlement"]] = relationship(
        back_populates="transaction", lazy="raise", cascade="all, delete-orphan"
    )
