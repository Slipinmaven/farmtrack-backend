from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class AppReleaseCreate(BaseModel):
    version: str = Field(
        pattern=r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$",
        max_length=40,
    )
    version_code: int = Field(gt=0, le=2_147_483_647)
    platform: Literal["android"] = "android"
    github_asset_id: int = Field(gt=0, le=9_223_372_036_854_775_807)
    release_notes: str | None = Field(default=None, max_length=10000)
    is_latest: bool = False


class AppReleaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version: str
    version_code: int
    platform: str
    github_asset_id: int | None
    file_name: str
    file_size: int | None
    release_notes: str | None
    is_active: bool
    is_latest: bool
    created_at: datetime
    updated_at: datetime


class GitHubReleaseAssetResponse(BaseModel):
    asset_id: int
    file_name: str
    file_size: int


class DownloadInvitationRequest(BaseModel):
    recipient_email: EmailStr


class DownloadInvitationRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    release_id: UUID
    recipient_email: EmailStr
    delivery_status: Literal["pending", "sent", "failed"]
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime
    last_accessed_at: datetime | None
    access_count: int


class DownloadInvitationResponse(BaseModel):
    id: UUID
    recipient_email: EmailStr
    delivery_status: Literal["sent"]
    expires_at: datetime
