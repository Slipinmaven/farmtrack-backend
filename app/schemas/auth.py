from datetime import datetime
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)


class LoginRequest(BaseModel):
    email: EmailStr
    password: SecretStr
    device_id: str = Field(min_length=16, max_length=128)
    device_name: str | None = Field(default=None, max_length=160)
    platform: str | None = Field(default=None, max_length=80)

    @field_validator("device_id")
    @classmethod
    def normalize_device_id(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 16:
            raise ValueError("A valid app installation ID is required.")
        return normalized


class RefreshRequest(BaseModel):
    refresh_token: SecretStr
    device_id: str | None = Field(default=None, min_length=16, max_length=128)
    device_name: str | None = Field(default=None, max_length=160)
    platform: str | None = Field(default=None, max_length=80)

    @field_validator("device_id")
    @classmethod
    def normalize_device_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if len(normalized) < 16:
            raise ValueError("A valid app installation ID is required.")
        return normalized


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr


class AuthenticationResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse


class PasswordChangeRequest(BaseModel):
    current_password: SecretStr
    new_password: SecretStr = Field(min_length=12, max_length=256)


class DeviceBlockRequest(BaseModel):
    permanent: bool = False
    duration_days: int | None = Field(default=None, ge=1, le=3650)

    @model_validator(mode="after")
    def validate_duration(self) -> "DeviceBlockRequest":
        if self.permanent and self.duration_days is not None:
            raise ValueError("Choose either a permanent block or a duration.")
        if not self.permanent and self.duration_days is None:
            raise ValueError("Choose a block duration.")
        return self


class UserSessionResponse(BaseModel):
    id: UUID
    device_name: str
    platform: str
    ip_address: str | None
    user_agent: str | None
    created_at: datetime
    last_seen_at: datetime
    revoked_at: datetime | None
    revocation_reason: str | None
    is_current: bool
    is_current_device: bool
    device_is_blocked: bool
    device_blocked_until: datetime | None
    device_blocked_permanently: bool


class BlockedDeviceResponse(BaseModel):
    id: UUID
    device_name: str
    is_permanent: bool
    is_active: bool
    blocked_until: datetime | None
    created_at: datetime
    updated_at: datetime


class SessionHistoryResponse(BaseModel):
    sessions: list[UserSessionResponse]
    blocked_devices: list[BlockedDeviceResponse]
    total: int
    offset: int
    limit: int
