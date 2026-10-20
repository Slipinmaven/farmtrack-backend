from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProductConsumptionAllocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    block_id: UUID | None = None
    batch_id: UUID | None = None


class ProductConsumptionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    unit_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    block_id: UUID | None = None
    batch_id: UUID | None = None
    consumption_date: date
    notes: str | None = None


class ProductConsumptionBatchCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    unit_id: UUID
    allocations: list[ProductConsumptionAllocationRequest] = Field(
        min_length=1,
        max_length=100,
    )
    consumption_date: date
    notes: str | None = None


class ProductConsumptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    farm_id: UUID
    product_id: UUID
    unit_id: UUID
    quantity: Decimal
    conversion_factor: Decimal
    quantity_in_base_unit: Decimal
    block_id: UUID | None
    batch_id: UUID | None
    consumption_date: date
    notes: str | None
    created_at: datetime
    updated_at: datetime