from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class UnitCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    abbreviation: str = Field(min_length=1, max_length=10)

    @field_validator("name", "abbreviation")
    @classmethod
    def strip_value(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value cannot be blank")
        return normalized


class UnitUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    abbreviation: str | None = Field(default=None, min_length=1, max_length=10)

    @field_validator("name", "abbreviation")
    @classmethod
    def strip_value(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("Value cannot be null")
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value cannot be blank")
        return normalized

    @model_validator(mode="after")
    def validate_patch(self) -> UnitUpdateRequest:
        if not self.model_fields_set:
            raise ValueError("At least one unit field must be provided.")
        return self


class UnitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    abbreviation: str
    created_at: datetime
    updated_at: datetime