from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SecuritySettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    biometric_unlock_enable: bool
    passcode_enabled: bool
    auto_lock_enabled: bool
    auto_lock_minutes: int
    created_at: datetime
    updated_at: datetime


class SecuritySettingsUpdate(BaseModel):
    biometric_unlock_enable: bool | None = None
    passcode_enabled: bool | None = None
    auto_lock_enabled: bool | None = None
    auto_lock_minutes: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_patch(self) -> SecuritySettingsUpdate:
        if not self.model_fields_set:
            raise ValueError("At least one security setting must be provided.")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Security settings cannot be null.")
        return self