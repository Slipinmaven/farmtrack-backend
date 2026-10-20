from datetime import date, time
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.payment import PaymentCreate


class EggSaleItemCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    unit_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    unit_price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)


class EggSaleCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_date: date | None = None
    transaction_time: time | None = None
    contact_id: UUID | None = None
    notes: str | None = None
    items: list[EggSaleItemCreateRequest] = Field(min_length=1)
    payments: list[PaymentCreate] = Field(default_factory=list)
    discount_type: Literal["fixed", "percentage"] | None = None
    discount_value: Decimal = Field(
        default=Decimal("0.00"), ge=0, max_digits=12, decimal_places=2
    )
    discount_reason: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_discount_terms(self) -> "EggSaleCreateRequest":
        if self.discount_type is None and self.discount_value != Decimal("0.00"):
            raise ValueError("Choose a discount type for the discount amount.")
        if self.discount_type == "percentage" and self.discount_value > 100:
            raise ValueError("A percentage discount cannot exceed 100%.")
        return self
