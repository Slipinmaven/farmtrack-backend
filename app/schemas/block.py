from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.enums import ChickenBatchStatus, ChickenType

class BlockCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    capacity: int = Field(ge=0)
    over_capacity_limit: int = Field(ge=0)
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name cannot be blank")
        return normalized


class BlockUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    capacity: int | None = Field(default=None, ge=0)
    over_capacity_limit: int | None = Field(default=None, ge=0)
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("name cannot be null")
        normalized = value.strip()
        if not normalized:
            raise ValueError("name cannot be blank")
        return normalized

    @model_validator(mode="after")
    def validate_patch(self) -> BlockUpdateRequest:
        if not self.model_fields_set:
            raise ValueError("At least one block field must be provided.")
        non_nullable_fields = {
            "name",
            "capacity",
            "over_capacity_limit",
            "is_active",
        }
        if any(
            field in self.model_fields_set and getattr(self, field) is None
            for field in non_nullable_fields
        ):
            raise ValueError("Block fields cannot be null.")
        return self


class BlockResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    farm_id: UUID
    name: str
    description: str | None
    capacity: int
    over_capacity_limit: int
    occupied_chickens: int = 0
    is_active: bool
    created_at: datetime
    updated_at: datetime


class BlockBatchOccupancyResponse(BaseModel):
    batch_id: UUID
    batch_name: str
    chicken_type: ChickenType
    breed: str | None
    status: ChickenBatchStatus
    hatch_date: date | None
    age_days: int | None
    quantity: int
    notes: str | None


class BlockDetailResponse(BlockResponse):
    batches: list[BlockBatchOccupancyResponse]