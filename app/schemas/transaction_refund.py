from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.enums import PaymentMethod

NonEmptyReason = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]


class TransactionRefundCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    refund_date: date
    refund_time: time | None = None
    payment_method: PaymentMethod
    reference_number: str | None = Field(default=None, max_length=100)
    reason: NonEmptyReason
    notes: str | None = None


class TransactionRefundResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    transaction_id: UUID
    amount: Decimal
    refund_date: date
    refund_time: time | None
    payment_method: PaymentMethod
    reference_number: str | None
    reason: str
    notes: str | None
    created_at: datetime


class TransactionRefundRecordResponse(BaseModel):
    refund: TransactionRefundResponse
    adjusted_transaction_total: Decimal
    amount_paid: Decimal
    balance_due: Decimal
    credit_balance: Decimal