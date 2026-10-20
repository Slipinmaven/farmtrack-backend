from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.schemas.chicken_purchase import BlockAllocationRequest, BlockAllocationResponse
from app.schemas.enums import ChickenType

NonEmptyReason = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]
PositiveQuantity = Annotated[
    Decimal,
    Field(gt=0, max_digits=12, decimal_places=3),
]


class PurchaseReturnItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_item_id: UUID
    quantity_returned: PositiveQuantity
    block_allocations: list[BlockAllocationRequest] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_allocations(self) -> "PurchaseReturnItemRequest":
        block_ids = [allocation.block_id for allocation in self.block_allocations]
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("Each block may appear only once per purchase return item.")
        if (
            self.block_allocations
            and sum(allocation.quantity for allocation in self.block_allocations)
            != self.quantity_returned
        ):
            raise ValueError("Block allocations must equal quantity_returned.")
        return self


class PurchaseReturnCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    return_date: date
    return_time: time | None = None
    reason: NonEmptyReason
    notes: str | None = None
    items: list[PurchaseReturnItemRequest] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_transaction_items(self) -> "PurchaseReturnCreateRequest":
        transaction_item_ids = [item.transaction_item_id for item in self.items]
        if len(transaction_item_ids) != len(set(transaction_item_ids)):
            raise ValueError("Each purchase item may appear only once per return.")
        return self


class PurchaseReturnItemResponse(BaseModel):
    id: UUID
    transaction_item_id: UUID
    product_id: UUID | None = None
    product_name: str | None = None
    batch_id: UUID | None = None
    chicken_type: ChickenType | None = None
    quantity_returned: Decimal
    credit_amount: Decimal
    block_allocations: list[BlockAllocationResponse]


class PurchaseReturnResponse(BaseModel):
    id: UUID
    transaction_id: UUID
    return_date: date
    return_time: time | None
    reason: str
    notes: str | None
    created_at: datetime
    credit_total: Decimal
    return_credit_remaining: Decimal
    adjusted_transaction_total: Decimal
    amount_paid: Decimal
    balance_due: Decimal
    credit_balance: Decimal
    items: list[PurchaseReturnItemResponse]


class PurchaseReturnHistoryResponse(BaseModel):
    id: UUID
    transaction_id: UUID
    return_date: date
    return_time: time | None
    reason: str
    notes: str | None
    created_at: datetime
    credit_total: Decimal
    items: list[PurchaseReturnItemResponse]