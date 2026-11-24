from datetime import datetime
from uuid import UUID

from pydantic import (
    AliasPath,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from app.schemas.enums import (
    FarmInvitationEmailStatus,
    FarmMembershipStatus,
    FarmRole,
)


class FarmMembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    farm_id: UUID
    user_id: UUID
    email: EmailStr | None = Field(
        default=None,
        validation_alias=AliasPath("user", "email"),
    )
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
    invitation_email_status: FarmInvitationEmailStatus
    invitation_email_sent_at: datetime | None


class FarmMemberInviteRequest(BaseModel):
    email: EmailStr
    role: FarmRole
    create_account: bool = False
    initial_password: SecretStr | None = Field(
        default=None,
        min_length=8,
        max_length=256,
    )

    @field_validator("role")
    @classmethod
    def owner_role_cannot_be_invited(cls, value: FarmRole) -> FarmRole:
        if value == FarmRole.OWNER:
            raise ValueError("Farm ownership cannot be assigned by invitation.")
        return value

    @model_validator(mode="after")
    def validate_account_creation(self) -> "FarmMemberInviteRequest":
        if self.create_account and self.initial_password is None:
            raise ValueError(
                "Enter an initial password of at least 8 characters for the new account."
            )
        if not self.create_account and self.initial_password is not None:
            raise ValueError(
                "An initial password can only be provided when creating a new account."
            )
        return self


class FarmMemberRoleUpdateRequest(BaseModel):
    role: FarmRole

    @field_validator("role")
    @classmethod
    def owner_role_cannot_be_assigned(cls, value: FarmRole) -> FarmRole:
        if value == FarmRole.OWNER:
            raise ValueError("Farm ownership cannot be assigned as a member role.")
        return value
