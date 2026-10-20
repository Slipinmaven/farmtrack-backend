from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.enums import PaymentMethod

class PaymentCreate(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    payment_date: date
    payment_time: time | None = None
    payment_method: PaymentMethod
    reference_number: str | None = Field(default=None, max_length=100)
    notes: str | None = None


class PaymentResponse(PaymentCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    transaction_id: UUID
    created_at: datetime
    updated_at: datetime


class PaymentRecordResponse(BaseModel):
    payment: PaymentResponse
    amount_paid: Decimal
    balance_due: Decimal
    credit_balance: Decimal