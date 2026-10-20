from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.chicken_purchase import BlockAllocationRequest, BlockAllocationResponse
from app.schemas.enums import ChickenType

PositiveQuantity = Annotated[int, Field(gt=0)]
NonNegativeQuantity = Annotated[int, Field(ge=0)]


class PurchaseReplacementItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purchase_return_item_id: UUID
    batch_id: UUID
    quantity_received: PositiveQuantity
    bonus_quantity: NonNegativeQuantity = 0
    credit_applied_amount: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    block_allocations: list[BlockAllocationRequest] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_allocation_and_settlement(self) -> "PurchaseReplacementItemRequest":
        if self.bonus_quantity > self.quantity_received:
            raise ValueError("bonus_quantity cannot exceed quantity_received.")
        if sum(allocation.quantity for allocation in self.block_allocations) != self.quantity_received:
            raise ValueError("Block allocations must equal quantity_received.")
        block_ids = [allocation.block_id for allocation in self.block_allocations]
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("Each block may appear only once per replacement item.")
        if self.credit_applied_amount == 0 and self.bonus_quantity != self.quantity_received:
            raise ValueError(
                "Replacement chickens must apply supplier credit; non-credited chickens must be marked as bonus quantity."
            )
        if self.credit_applied_amount > 0 and self.bonus_quantity == self.quantity_received:
            raise ValueError("Bonus-only chickens cannot apply supplier credit.")
        return self


class PurchaseReplacementCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    replacement_date: date
    replacement_time: time | None = None
    purchase_return_id: UUID
    notes: str | None = None
    items: list[PurchaseReplacementItemRequest] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_return_items(self) -> "PurchaseReplacementCreateRequest":
        return_item_ids = [item.purchase_return_item_id for item in self.items]
        if len(return_item_ids) != len(set(return_item_ids)):
            raise ValueError("Each purchase return item may appear only once per replacement.")
        return self


class PurchaseReplacementItemResponse(BaseModel):
    id: UUID
    purchase_return_item_id: UUID
    batch_id: UUID
    chicken_type: ChickenType
    quantity_received: Decimal
    replacement_quantity: Decimal
    bonus_quantity: Decimal
    credit_applied_amount: Decimal
    block_allocations: list[BlockAllocationResponse]


class PurchaseReplacementResponse(BaseModel):
    id: UUID
    purchase_return_id: UUID
    transaction_id: UUID
    replacement_date: date
    replacement_time: time | None
    notes: str | None
    created_at: datetime
    credit_applied_total: Decimal
    return_credit_remaining: Decimal
    adjusted_transaction_total: Decimal
    amount_paid: Decimal
    balance_due: Decimal
    credit_balance: Decimal
    items: list[PurchaseReplacementItemResponse]


class PurchaseReplacementHistoryResponse(BaseModel):
    id: UUID
    purchase_return_id: UUID
    transaction_id: UUID
    replacement_date: date
    replacement_time: time | None
    notes: str | None
    created_at: datetime
    credit_applied_total: Decimal
    items: list[PurchaseReplacementItemResponse]