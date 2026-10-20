from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.enums import ChickenType

PositiveQuantity = Annotated[int, Field(gt=0)]


class SaleDeliveryBatchAllocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: UUID
    block_id: UUID
    quantity: PositiveQuantity


class SaleDeliveryItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_item_id: UUID
    quantity_delivered: PositiveQuantity
    batch_allocations: list[SaleDeliveryBatchAllocation] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_allocations(self) -> "SaleDeliveryItemRequest":
        if sum(allocation.quantity for allocation in self.batch_allocations) != self.quantity_delivered:
            raise ValueError("Batch allocations must equal quantity_delivered.")

        allocation_pairs = [
            (allocation.batch_id, allocation.block_id)
            for allocation in self.batch_allocations
        ]
        if len(allocation_pairs) != len(set(allocation_pairs)):
            raise ValueError("Each batch and block pair may appear only once per delivery item.")

        return self


class SaleDeliveryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delivered_date: date
    delivered_time: time | None = None
    notes: str | None = None
    items: list[SaleDeliveryItemRequest] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_transaction_items(self) -> "SaleDeliveryCreateRequest":
        item_ids = [item.transaction_item_id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("Each sale item may appear only once per delivery.")
        return self


class SaleDeliveryAllocationResponse(BaseModel):
    batch_id: UUID
    block_id: UUID
    quantity: int


class SaleDeliveryItemResponse(BaseModel):
    id: UUID
    transaction_item_id: UUID
    quantity_delivered: Decimal
    remaining_quantity: Decimal
    batch_allocations: list[SaleDeliveryAllocationResponse]
    chicken_type: ChickenType | None = None


class SaleDeliveryResponse(BaseModel):
    id: UUID
    transaction_id: UUID
    delivered_date: date
    delivered_time: time | None
    notes: str | None
    created_at: datetime
    items: list[SaleDeliveryItemResponse]


class SaleFulfillmentItemResponse(BaseModel):
    transaction_item_id: UUID
    chicken_type: ChickenType | None
    ordered_quantity: Decimal
    delivered_quantity: Decimal
    returned_quantity: Decimal
    net_delivered_quantity: Decimal
    cancelled_quantity: Decimal
    outstanding_quantity: Decimal


class SaleFulfillmentResponse(BaseModel):
    transaction_id: UUID
    fully_delivered: bool
    fully_resolved: bool
    items: list[SaleFulfillmentItemResponse]
