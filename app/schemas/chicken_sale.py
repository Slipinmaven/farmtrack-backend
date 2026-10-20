from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.enums import ChickenType
from app.schemas.payment import PaymentCreate
from app.schemas.product import ProductResponse
from app.schemas.transaction import TransactionResponse


class ChickenSaleBlockOption(BaseModel):
    id: UUID
    name: str
    capacity: int
    over_capacity_limit: int
    maximum_chickens: int
    current_chickens: int
    available_capacity: int


class ChickenSaleBatchStock(BaseModel):
    block_id: UUID
    block_name: str
    quantity: int


class ChickenSaleBatchOption(BaseModel):
    id: UUID
    name: str
    chicken_type: ChickenType
    hatch_date: date | None
    estimated_unit_cost: Decimal | None = None
    stocks: list[ChickenSaleBatchStock]


PositiveQuantity = Annotated[int, Field(gt=0)]


class ChickenSaleBatchAllocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: UUID
    block_id: UUID
    quantity: PositiveQuantity


class ChickenSaleItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    chicken_type: ChickenType
    quantity: PositiveQuantity
    unit_id: UUID
    unit_price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    notes: str | None = None
    batch_allocations: list[ChickenSaleBatchAllocation] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_batch_allocations(self) -> "ChickenSaleItemCreate":
        if not self.batch_allocations:
            return self

        allocation_pairs = [
            (allocation.batch_id, allocation.block_id)
            for allocation in self.batch_allocations
        ]
        if len(allocation_pairs) != len(set(allocation_pairs)):
            raise ValueError("Each batch and block pair may appear only once per sale item.")

        return self


class ChickenSaleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_date: date | None = None
    transaction_time: time | None = None
    notes: str | None = None
    customer_id: UUID | None = None
    items: list[ChickenSaleItemCreate] = Field(min_length=1)
    payments: list[PaymentCreate] = Field(default_factory=list)
    discount_type: Literal["fixed", "percentage"] | None = None
    discount_value: Decimal = Field(
        default=Decimal("0.00"), ge=0, max_digits=12, decimal_places=2
    )
    discount_reason: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_discount_terms(self) -> "ChickenSaleRequest":
        if self.discount_type is None and self.discount_value != Decimal("0.00"):
            raise ValueError("Choose a discount type for the discount amount.")
        if (
            self.discount_type == "percentage"
            and self.discount_value > Decimal("100.00")
        ):
            raise ValueError("A percentage discount cannot exceed 100%.")
        return self


class ChickenSaleResponse(TransactionResponse):
    pass


class ChickenSaleAllocationDetailResponse(BaseModel):
    batch_id: UUID
    batch_name: str
    block_id: UUID
    block_name: str
    quantity: int


class ChickenSaleDeliveryItemDetailResponse(BaseModel):
    id: UUID
    transaction_item_id: UUID
    quantity: Decimal
    batch_allocations: list[ChickenSaleAllocationDetailResponse]


class ChickenSaleDeliveryDetailResponse(BaseModel):
    id: UUID
    delivered_date: date
    delivered_time: time | None
    notes: str | None
    items: list[ChickenSaleDeliveryItemDetailResponse]


class ChickenSaleOutstandingBalanceResponse(BaseModel):
    id: UUID
    reference_number: str | None
    transaction_date: date
    transaction_total: Decimal
    amount_paid: Decimal
    balance_due: Decimal
    credit_balance: Decimal


class ChickenSaleDetailResponse(BaseModel):
    transaction: ChickenSaleResponse
    customer_name: str | None
    deliveries: list[ChickenSaleDeliveryDetailResponse]
    outstanding_customer_balances: list[ChickenSaleOutstandingBalanceResponse]
    customer_balance_total: Decimal
    customer_credit_total: Decimal


class ChickenSaleOptionsResponse(BaseModel):
    products: list[ProductResponse]
    blocks: list[ChickenSaleBlockOption]
    batches: list[ChickenSaleBatchOption]
