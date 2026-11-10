from datetime import date, time
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class AccountLedgerComponent(BaseModel):
    kind: Literal["cash", "goods", "service"]
    label: str
    amount: Decimal
    payment_method: str | None = None
    reference_number: str | None = None


class AccountLedgerEvent(BaseModel):
    id: str
    transaction_id: UUID
    transaction_type: Literal["sale", "purchase"]
    contact_id: UUID | None
    contact_name: str | None
    event_type: Literal[
        "transaction",
        "payment",
        "settlement",
        "return",
        "refund",
        "replacement",
    ]
    event_date: date
    event_time: time | None = None
    reference_number: str | None
    description: str
    amount: Decimal
    running_balance: Decimal
    cash_amount: Decimal | None = None
    payment_method: str | None = None
    payment_reference: str | None = None
    components: list[AccountLedgerComponent] = Field(default_factory=list)


class AccountLedgerAccount(BaseModel):
    contact_id: UUID | None
    contact_name: str
    roles: list[Literal["customer", "supplier"]]
    balance: Decimal
    last_activity: date | None


class AccountLedgerResponse(BaseModel):
    events: list[AccountLedgerEvent]
    accounts: list[AccountLedgerAccount]
    opening_balance: Decimal | None
    closing_balance: Decimal | None
