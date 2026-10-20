from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.enums import ChickenType


class OpeningChickenAllocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_id: UUID
    quantity: int = Field(gt=0)


class OpeningChickenBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    chicken_type: ChickenType
    breed: str | None = Field(default=None, max_length=100)
    hatch_date: date | None = None
    unit_cost: Decimal | None = Field(
        default=None, ge=0, max_digits=14, decimal_places=6,
        description="Recorded acquisition cost per chicken; omitted means unvalued stock.",
    )
    allocations: list[OpeningChickenAllocationRequest] = Field(min_length=1)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Batch name cannot be blank.")
        return normalized


class OpeningEggStockRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    block_id: UUID
    unit_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    unit_cost: Decimal | None = Field(
        default=None, ge=0, max_digits=14, decimal_places=6,
        description="Recorded cost per selected unit; omitted means unvalued stock.",
    )


class InventoryOpeningSetupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    species: Literal["chickens", "eggs"]
    setup_date: date
    chicken_batches: list[OpeningChickenBatchRequest] = Field(default_factory=list)
    egg_stock: list[OpeningEggStockRequest] = Field(default_factory=list)


class InventoryOpeningSetupSpeciesStatus(BaseModel):
    eligible: bool
    completed_at: date | None = None


class InventoryOpeningSetupStatusResponse(BaseModel):
    chickens: InventoryOpeningSetupSpeciesStatus
    eggs: InventoryOpeningSetupSpeciesStatus


class InventoryOpeningSetupResponse(BaseModel):
    species: Literal["chickens", "eggs"]
    setup_date: date
    record_count: int
