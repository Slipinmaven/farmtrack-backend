from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.enums import ProductType


class EggCollectionItemCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    block_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    unit_id: UUID
    notes: str | None = None


class EggCollectionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collected_at: datetime
    items: list[EggCollectionItemCreateRequest] = Field(min_length=1)

    @field_validator("collected_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("collected_at must include a timezone.")
        return value

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_single_entry(cls, value):
        if isinstance(value, dict) and "items" not in value:
            required_legacy_fields = {
                "product_id",
                "block_id",
                "quantity",
                "unit_id",
            }
            legacy_fields = required_legacy_fields | {"notes"}
            if required_legacy_fields.issubset(value):
                return {
                    "collected_at": value.get("collected_at"),
                    "items": [
                        {key: value[key] for key in legacy_fields if key in value}
                    ],
                }
        return value


class EggCollectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    farm_id: UUID
    product_id: UUID
    block_id: UUID | None
    quantity: Decimal
    unit_id: UUID
    conversion_factor: Decimal
    quantity_in_base_unit: Decimal
    collected_at: datetime
    entry_type: Literal["collection", "opening_stock"]
    notes: str | None
    created_at: datetime
    updated_at: datetime


class EggCollectionUnitOption(BaseModel):
    id: UUID
    name: str
    abbreviation: str
    conversion_factor: Decimal
    is_base_unit: bool


class EggCollectionOptionsProduct(BaseModel):
    id: UUID
    name: str
    product_type: ProductType
    is_sellable: bool
    units: list[EggCollectionUnitOption]
    collected_quantity_in_base_unit: Decimal
    lost_quantity_in_base_unit: Decimal
    sold_quantity_in_base_unit: Decimal
    available_quantity_in_base_unit: Decimal


class EggCollectionOptionsBlock(BaseModel):
    id: UUID
    name: str
    is_active: bool


class EggCollectionOptionsResponse(BaseModel):
    products: list[EggCollectionOptionsProduct]
    blocks: list[EggCollectionOptionsBlock]