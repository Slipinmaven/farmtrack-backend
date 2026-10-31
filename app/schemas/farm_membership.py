from datetime import datetime
from uuid import UUID

from pydantic import AliasPath, BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.schemas.enums import FarmMembershipStatus, FarmRole


class FarmMembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    farm_id: UUID
    user_id: UUID
    email: EmailStr = Field(validation_alias=AliasPath("user", "email"))
    farm_name: str | None = Field(
        default=None,
        validation_alias=AliasPath("farm", "name"),
    )
    role: FarmRole
    status: FarmMembershipStatus
    invited_by_id: UUID | None
    invited_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None


class FarmMemberInviteRequest(BaseModel):
    email: EmailStr
    role: FarmRole

    @field_validator("role")
    @classmethod
    def owner_role_cannot_be_invited(cls, value: FarmRole) -> FarmRole:
        if value == FarmRole.OWNER:
            raise ValueError("Farm ownership cannot be assigned by invitation.")
        return value


class FarmMemberRoleUpdateRequest(BaseModel):
    role: FarmRole

    @field_validator("role")
    @classmethod
    def owner_role_cannot_be_assigned(cls, value: FarmRole) -> FarmRole:
        if value == FarmRole.OWNER:
            raise ValueError("Farm ownership cannot be assigned as a member role.")
        return value
