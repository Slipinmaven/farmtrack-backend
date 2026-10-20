from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

from app.schemas.enums import (
    ContactRoleEnum,
    ProductType,
    TransactionStatus,
    TransactionType,
)


class ContactCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    role: ContactRoleEnum
    phone: str | None = Field(default=None, max_length=30)
    email: EmailStr | None = Field(default=None, max_length=255)
    address: str | None = Field(default=None, max_length=255)
    notes: str | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name cannot be blank")
        return normalized


class ContactUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    phone: str | None = Field(default=None, max_length=30)
    email: EmailStr | None = Field(default=None, max_length=255)
    address: str | None = Field(default=None, max_length=255)
    notes: str | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("name cannot be null")
        normalized = value.strip()
        if not normalized:
            raise ValueError("name cannot be blank")
        return normalized

    @model_validator(mode="after")
    def validate_patch(self) -> ContactUpdateRequest:
        if not self.model_fields_set:
            raise ValueError("At least one contact field must be provided.")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name cannot be null")
        return self


class ContactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    farm_id: UUID
    name: str
    roles: list[ContactRoleEnum]
    phone: str | None
    email: str | None
    address: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class ContactTransactionHistoryItem(BaseModel):
    id: UUID
    transaction_type: TransactionType
    status: TransactionStatus
    transaction_date: date
    reference_number: str | None
    item_count: int
    transaction_total: Decimal
    amount_paid: Decimal
    balance_due: Decimal
    credit_balance: Decimal


class ContactTransactionHistoryResponse(BaseModel):
    items: list[ContactTransactionHistoryItem]
    total_count: int
    limit: int
    offset: int


class ContactRoleCreateRequest(BaseModel):
    role: ContactRoleEnum


class ContactRoleUpdateRequest(BaseModel):
    role: ContactRoleEnum | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> ContactRoleUpdateRequest:
        if "role" not in self.model_fields_set:
            raise ValueError("A contact role must be provided.")
        if self.role is None:
            raise ValueError("role cannot be null")
        return self


class ContactRoleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    contact_id: UUID
    role: ContactRoleEnum
    created_at: datetime
    updated_at: datetime


class ContactRoleProductCreateRequest(BaseModel):
    product_id: UUID


class ContactRoleProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    association_id: UUID
    product_id: UUID
    product_name: str
    product_type: ProductType
    is_active: bool
    created_at: datetime