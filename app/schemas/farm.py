from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID
from pydantic import (
    AliasPath,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)
from app.schemas.enums import ThemeMode

class FarmResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    owner_id: UUID
    name: str
    description: str | None
    location: str | None
    phone_number: str | None
    email: str | None
    maximum_chicken_capacity: int | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    settings: FarmSettingsResponse | None = Field(
        default=None,
        validation_alias=AliasPath("farm_settings"),
    )

class FarmCreateRequest(BaseModel): 
    name: str = Field(..., max_length=150)
    description: str | None = None
    location: str | None = Field(default=None, max_length=255)
    phone_number: str | None = Field(default=None, max_length=20)
    email: EmailStr | None = Field(default=None, max_length=255)
    maximum_chicken_capacity: int | None = Field(default=None, gt=0)
    settings: FarmSettingsCreate | None = None


class FarmUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=150)
    description: str | None = None
    location: str | None = Field(default=None, max_length=255)
    phone_number: str | None = Field(default=None, max_length=20)
    email: EmailStr | None = Field(default=None, max_length=255)
    maximum_chicken_capacity: int | None = Field(default=None, gt=0)
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("name cannot be null")
        normalized = value.strip()
        if not normalized:
            raise ValueError("name cannot be blank")
        return normalized

    @model_validator(mode="after")
    def require_update_fields(self) -> FarmUpdateRequest:
        if not self.model_fields_set:
            raise ValueError("At least one farm field must be provided.")
        return self


class FarmSettingsCreate(BaseModel):
    primary_color: str | None = Field(default=None, max_length=7)
    secondary_color: str | None = Field(default=None, max_length=7)
    font_family: str | None = Field(default=None, max_length=50)
    font_scale: Decimal | None = Field(default=None, max_digits=3, decimal_places=2)
    theme_mode: ThemeMode | None = Field(default=None)
    logo_path: str | None = None
    currency: str | None = Field(default=None, max_length=3)
    timezone: str | None = Field(default=None, max_length=50)

class FarmSettingsUpdate(BaseModel):
    primary_color: str | None = Field(default=None, max_length=7)
    secondary_color: str | None = Field(default=None, max_length=7)
    font_family: str | None = Field(default=None, max_length=50)
    font_scale: Decimal | None = Field(default=None, max_digits=3, decimal_places=2)
    theme_mode: ThemeMode | None = Field(default=None)
    logo_path: str | None = None
    currency: str | None = Field(default=None, max_length=3)
    timezone: str | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def require_update_fields(self) -> FarmSettingsUpdate:
        if not self.model_fields_set:
            raise ValueError("At least one farm setting must be provided.")
        return self


class FarmSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    farm_id: UUID
    primary_color: str | None
    secondary_color: str | None
    font_family: str | None
    font_scale: Decimal | None
    theme_mode: ThemeMode | None
    logo_path: str | None
    currency: str | None
    timezone: str | None
    created_at: datetime
    updated_at: datetime
