from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.enums import (
    ChickenType,
    ProductType,
    TransactionStatus,
    TransactionType,
)
from app.schemas.payment import PaymentCreate, PaymentResponse


class TransactionItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    unit_id: UUID
    chicken_type: ChickenType | None = None
    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    unit_price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    notes: str | None = None
    batch_allocations: list[dict] | None = None


class TransactionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_type: TransactionType
    transaction_date: date | None = None
    transaction_time: time | None = None
    status: TransactionStatus = TransactionStatus.COMPLETED
    fulfillment_required: bool = False
    contact_id: UUID | None = None
    notes: str | None = None
    items: list[TransactionItemCreate] = Field(min_length=1)
    payments: list[PaymentCreate] = Field(default_factory=list)
    discount_type: Literal["fixed", "percentage"] | None = None
    discount_value: Decimal = Field(
        default=Decimal("0.00"), ge=0, max_digits=12, decimal_places=2
    )
    discount_reason: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_discount_terms(self) -> "TransactionCreate":
        if self.discount_type is None and self.discount_value != Decimal("0.00"):
            raise ValueError("Choose a discount type for the discount amount.")
        if (
            self.discount_type == "percentage"
            and self.discount_value > Decimal("100.00")
        ):
            raise ValueError("A percentage discount cannot exceed 100%.")
        return self


class TransactionItemResponse(BaseModel):
    id: UUID
    product_id: UUID
    unit_id: UUID
    quantity: Decimal
    conversion_factor: Decimal
    chicken_type: ChickenType | None
    ordered_base_quantity: Decimal
    unit_price: Decimal
    subtotal_amount: Decimal
    discount_amount: Decimal
    total_amount: Decimal
    notes: str | None
    quantity_received: Decimal
    quantity_remaining: Decimal
    product_name: str | None = None
    product_type: ProductType | None = None
    unit_name: str | None = None


class TransactionResponse(BaseModel):
    id: UUID
    farm_id: UUID
    contact_id: UUID | None
    transaction_type: TransactionType
    status: TransactionStatus
    transaction_date: date
    transaction_time: time | None = None
    reference_number: str | None
    notes: str | None
    discount_type: Literal["fixed", "percentage"] | None = None
    discount_value: Decimal = Decimal("0.00")
    discount_amount: Decimal = Decimal("0.00")
    discount_reason: str | None = None
    items: list[TransactionItemResponse]
    payments: list[PaymentResponse]
    transaction_total: Decimal
    amount_paid: Decimal
    balance_due: Decimal
    credit_balance: Decimal
    created_at: datetime
    updated_at: datetime