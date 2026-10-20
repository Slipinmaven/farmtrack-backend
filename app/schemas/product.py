from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.enums import ProductType


class ProductUnitCreateRequest(BaseModel):
    unit_id: UUID
    conversion_factor: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    is_base_unit: bool = False


class ProductCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    product_type: ProductType
    description: str | None = None
    is_active: bool = True
    is_sellable: bool = False
    product_units: list[ProductUnitCreateRequest] = Field(min_length=1)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Product name cannot be blank")
        return normalized

    @model_validator(mode="after")
    def validate_product_units(self) -> ProductCreateRequest:
        _validate_product_units(self.product_units)
        return self


class ProductUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    product_type: ProductType | None = None
    description: str | None = None
    is_active: bool | None = None
    is_sellable: bool | None = None
    product_units: list[ProductUnitCreateRequest] | None = Field(default=None, min_length=1)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("Product name cannot be null")
        normalized = value.strip()
        if not normalized:
            raise ValueError("Product name cannot be blank")
        return normalized

    @field_validator("product_type", "is_active", "is_sellable")
    @classmethod
    def reject_null_values(cls, value):
        if value is None:
            raise ValueError("Field cannot be null")
        return value

    @field_validator("product_units")
    @classmethod
    def reject_null_product_units(
        cls,
        value: list[ProductUnitCreateRequest] | None,
    ) -> list[ProductUnitCreateRequest]:
        if value is None:
            raise ValueError("Product units cannot be null")
        return value

    @model_validator(mode="after")
    def validate_patch(self) -> ProductUpdateRequest:
        if not self.model_fields_set:
            raise ValueError("At least one product field must be provided.")
        if self.product_units is not None:
            _validate_product_units(self.product_units)
        return self


class ProductUnitResponse(BaseModel):
    id: UUID
    unit_id: UUID
    unit_name: str
    unit_abbreviation: str
    conversion_factor: Decimal
    is_base_unit: bool


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    farm_id: UUID
    name: str
    product_type: ProductType
    description: str | None
    is_active: bool
    is_sellable: bool
    product_units: list[ProductUnitResponse]
    created_at: datetime
    updated_at: datetime


def _validate_product_units(units: list[ProductUnitCreateRequest]) -> None:
    unit_ids = [unit.unit_id for unit in units]
    if len(unit_ids) != len(set(unit_ids)):
        raise ValueError("A unit may only be added once to a product")

    base_units = [unit for unit in units if unit.is_base_unit]
    if len(base_units) != 1:
        raise ValueError("Exactly one product unit must be the base unit")
    if base_units[0].conversion_factor != Decimal("1"):
        raise ValueError("The base unit conversion factor must be 1")
