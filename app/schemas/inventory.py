from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.enums import InventoryMovementType, ProductType
from app.schemas.payment import PaymentCreate


InventoryNote = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]


class InventoryAdjustmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    unit_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    direction: Literal["in", "out"]
    occurred_on: date
    reason: InventoryNote
    unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=6)


class InventoryPurchaseItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    unit_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    unit_price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)


class InventoryPurchaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_date: date
    supplier_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=500)
    items: list[InventoryPurchaseItemRequest] = Field(min_length=1)
    payments: list[PaymentCreate] = Field(default_factory=list)


class InventoryMovementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    product_name: str
    product_type: ProductType
    quantity_delta: Decimal
    unit_name: str
    unit_abbreviation: str
    movement_type: InventoryMovementType
    source_type: str | None
    source_id: UUID | None
    source_item_id: UUID | None
    unit_cost: Decimal | None = None
    occurred_on: date
    notes: str | None
    created_at: datetime


class InventoryProductBalance(BaseModel):
    product_id: UUID
    product_name: str
    product_type: ProductType
    quantity: Decimal
    unit_name: str
    unit_abbreviation: str


class InventoryOverviewResponse(BaseModel):
    items: list[InventoryProductBalance]
    movements: list[InventoryMovementResponse]
