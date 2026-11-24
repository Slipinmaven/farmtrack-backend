from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, model_validator

from app.schemas.enums import PaymentMethod, TransactionStatus, TransactionType


class ReceiptHistoryPayment(BaseModel):
    id: UUID
    payment_number: int
    payment_date: date
    reference_number: str | None
    amount: Decimal
    payment_method: PaymentMethod


class ReceiptHistoryLineItem(BaseModel):
    product_name: str
    quantity: Decimal
    unit_name: str


class ReceiptHistoryTransaction(BaseModel):
    id: UUID
    transaction_type: TransactionType
    status: TransactionStatus
    transaction_date: date
    reference_number: str | None
    contact_name: str | None
    product_names: list[str]
    line_items: list[ReceiptHistoryLineItem]
    transaction_total: Decimal
    payments: list[ReceiptHistoryPayment]


class ReceiptHistoryResponse(BaseModel):
    items: list[ReceiptHistoryTransaction]
    total_count: int
    completed_total: Decimal = Decimal("0.00")
    offset: int
    limit: int


class ReceiptHistoryFilters(BaseModel):
    search: str | None = None
    transaction_type: Literal["all", "sale", "purchase"] = "all"
    receipt_kind: Literal["all", "transaction", "payment"] = "all"
    status: Literal["all", "completed", "cancelled"] = "all"
    from_date: date | None = None
    to_date: date | None = None

    @model_validator(mode="after")
    def validate_date_range(self) -> "ReceiptHistoryFilters":
        if (
            self.from_date is not None
            and self.to_date is not None
            and self.from_date > self.to_date
        ):
            raise ValueError("The start date must be on or before the end date.")
        return self
