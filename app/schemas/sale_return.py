from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.schemas.enums import SaleReturnType
from app.schemas.sale_delivery import SaleDeliveryAllocationResponse

PositiveQuantity = Annotated[
    Decimal,
    Field(gt=0, max_digits=12, decimal_places=3),
]
PositiveCount = Annotated[int, Field(gt=0)]
NonEmptyReason = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]


class SaleReturnAllocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: UUID
    block_id: UUID
    quantity: PositiveCount


class SaleReturnItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_item_id: UUID
    quantity: PositiveQuantity
    batch_allocations: list[SaleReturnAllocationRequest] = Field(default_factory=list)


class SaleReturnCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    return_type: SaleReturnType
    return_date: date
    return_time: time | None = None
    reason: NonEmptyReason
    notes: str | None = None
    items: list[SaleReturnItemRequest] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_items(self) -> "SaleReturnCreateRequest":
        transaction_item_ids = [item.transaction_item_id for item in self.items]
        if len(transaction_item_ids) != len(set(transaction_item_ids)):
            raise ValueError("Each sale item may appear only once per return.")

        for item in self.items:
            pairs = [
                (allocation.batch_id, allocation.block_id)
                for allocation in item.batch_allocations
            ]
            if len(pairs) != len(set(pairs)):
                raise ValueError("Each batch and block pair may appear only once per returned item.")

            if (
                self.return_type == SaleReturnType.DELIVERED_RETURN
                and item.batch_allocations
                and sum(allocation.quantity for allocation in item.batch_allocations)
                != item.quantity
            ):
                raise ValueError(
                    "Return allocations must equal the returned quantity."
                )
            elif (
                self.return_type == SaleReturnType.UNDELIVERED_CANCELLED
                and item.batch_allocations
            ):
                raise ValueError(
                    "Undelivered cancellations must not change inventory allocations."
                )

        return self


class SaleReturnItemResponse(BaseModel):
    id: UUID
    transaction_item_id: UUID
    product_id: UUID | None = None
    product_name: str | None = None
    quantity: Decimal
    credit_amount: Decimal
    batch_allocations: list[SaleDeliveryAllocationResponse]


class SaleReturnHistoryResponse(BaseModel):
    id: UUID
    transaction_id: UUID
    return_type: SaleReturnType
    return_date: date
    return_time: time | None
    reason: str
    notes: str | None
    created_at: datetime
    credit_total: Decimal
    items: list[SaleReturnItemResponse]


class SaleReturnResponse(SaleReturnHistoryResponse):
    adjusted_transaction_total: Decimal
    amount_paid: Decimal
    balance_due: Decimal
    credit_balance: Decimal