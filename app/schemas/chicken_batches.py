from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator
from app.schemas.enums import ChickenType, ChickenBatchStatus

class ChickenBatchesCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    chicken_type: ChickenType
    breed: str | None = Field(default=None, max_length=100)
    acquisition_date: date
    status: ChickenBatchStatus
    notes: str | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name cannot be blank")
        return normalized