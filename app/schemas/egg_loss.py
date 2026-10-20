from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.enums import EggLossReason


class EggLossCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    unit_id: UUID
    loss_date: date
    reason: EggLossReason
    notes: str | None = None


class EggLossBatchItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    unit_id: UUID


class EggLossBatchCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    loss_date: date
    reason: EggLossReason
    items: list[EggLossBatchItemRequest] = Field(min_length=1)
    notes: str | None = None

    @model_validator(mode="after")
    def validate_unique_units(self) -> "EggLossBatchCreateRequest":
        unit_ids = [item.unit_id for item in self.items]
        if len(unit_ids) != len(set(unit_ids)):
            raise ValueError("Each unit can only be listed once per egg loss.")
        return self


class EggLossResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    farm_id: UUID
    product_id: UUID
    quantity: Decimal
    unit_id: UUID
    conversion_factor: Decimal
    quantity_in_base_unit: Decimal
    loss_date: date
    reason: EggLossReason
    notes: str | None
    created_at: datetime
    updated_at: datetime