from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    Numeric,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.schemas.enums import ChickenType

if TYPE_CHECKING:
    from app.models.chicken_transaction_items import ChickenTransactionItem
    from app.models.products import Product
    from app.models.purchase_receipt_items import PurchaseReceiptItem
    from app.models.transactions import Transaction
    from app.models.units import Unit


class TransactionItem(Base):
    __tablename__ = "transaction_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_transaction_items_quantity_positive"),
        CheckConstraint(
            "conversion_factor > 0",
            name="ck_transaction_items_conversion_factor_positive",
        ),
        CheckConstraint("unit_price >= 0", name="ck_transaction_items_unit_price_non_negative"),
        CheckConstraint(
            "total_amount >= 0",
            name="ck_transaction_items_total_amount_non_negative",
        ),
        CheckConstraint(
            "subtotal_amount >= 0 AND discount_amount >= 0 AND discount_amount <= subtotal_amount",
            name="ck_transaction_items_discount_amount_valid",
        ),
        CheckConstraint(
            "total_amount = subtotal_amount - discount_amount",
            name="ck_transaction_items_total_matches_discounted_subtotal",
        ),
        Index("ix_transaction_items_transaction_id", "transaction_id"),
        Index("ix_transaction_items_product_id", "product_id"),
        Index("ix_transaction_items_unit_id", "unit_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    transaction_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("transactions.id"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("products.id"), nullable=False
    )
    unit_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("units.id"), nullable=False
    )
    chicken_type: Mapped[ChickenType | None] = mapped_column(
        SQLEnum(ChickenType, name="chickentype"), nullable=True
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    conversion_factor: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    subtotal_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    transaction: Mapped["Transaction"] = relationship(
        back_populates="items", lazy="raise"
    )
    product: Mapped["Product"] = relationship(
        back_populates="transaction_items", lazy="raise"
    )
    unit: Mapped["Unit"] = relationship(
        back_populates="transaction_items", lazy="raise"
    )
    chicken_transaction_item: Mapped["ChickenTransactionItem | None"] = relationship(
        back_populates="transaction_item", lazy="raise", cascade="all, delete-orphan"
    )
    purchase_receipt_items: Mapped[list["PurchaseReceiptItem"]] = relationship(
        back_populates="transaction_item", lazy="raise"
    )
