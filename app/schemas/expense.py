from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.enums import PaymentMethod


class ExpensePaymentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    payment_date: date
    payment_method: PaymentMethod
    reference_number: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_reference(self):
        if (
            self.payment_method != PaymentMethod.CASH
            and not (self.reference_number or "").strip()
        ):
            raise ValueError("A payment reference is required for non-cash payments.")
        if self.reference_number is not None:
            self.reference_number = self.reference_number.strip() or None
        return self


class ExpenseRefundCreateRequest(ExpensePaymentCreateRequest):
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("A meaningful refund reason is required.")
        return value


class ExpenseCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=80)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    expense_date: date
    contact_id: UUID | None = None
    block_id: UUID | None = None
    receipt_reference: str | None = Field(default=None, max_length=500)
    notes: str | None = None
    initial_payment: ExpensePaymentCreateRequest | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("An expense name is required.")
        return value

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("An expense category is required.")
        return value


class ExpenseUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    category: str | None = Field(default=None, min_length=1, max_length=80)
    amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    expense_date: date | None = None
    contact_id: UUID | None = None
    block_id: UUID | None = None
    receipt_reference: str | None = Field(default=None, max_length=500)
    notes: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("An expense name cannot be empty.")
        return value

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("An expense category cannot be empty.")
        return value

    @model_validator(mode="after")
    def validate_non_nullable_fields(self):
        for field in ("name", "category", "amount", "expense_date"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null.")
        return self


class ExpenseCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("A meaningful cancellation reason is required.")
        return value


class ExpensePaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    amount: Decimal
    payment_date: date
    payment_method: PaymentMethod
    reference_number: str | None
    reason: str | None
    created_at: datetime


class ExpenseResponse(BaseModel):
    id: UUID
    farm_id: UUID
    name: str
    category: str
    category_name: str
    amount: Decimal
    amount_paid: Decimal
    balance_due: Decimal
    payment_status: str
    expense_date: date
    contact_id: UUID | None
    contact_name: str | None
    block_id: UUID | None
    block_name: str | None
    purchase_transaction_id: UUID | None
    purchase_reference: str | None
    receipt_reference: str | None
    notes: str | None
    payments: list[ExpensePaymentResponse]
    canceled_at: datetime | None
    cancellation_reason: str | None
    created_at: datetime
    updated_at: datetime


class ExpenseListResponse(BaseModel):
    items: list[ExpenseResponse]
    total_count: int
    offset: int
    limit: int


class ExpenseSummaryCategory(BaseModel):
    key: str
    name: str
    expense_count: int
    total_amount: Decimal
    amount_paid: Decimal
    balance_due: Decimal


class ExpenseSummaryResponse(BaseModel):
    expense_count: int
    total_amount: Decimal
    amount_paid: Decimal
    balance_due: Decimal
    categories: list[ExpenseSummaryCategory]


class ExpenseCategoryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=80)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("A category name must have at least two characters.")
        return value


class ExpenseCategoryUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=2, max_length=80)
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if len(value) < 2:
            raise ValueError("A category name must have at least two characters.")
        return value


class ExpenseCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    key: str
    name: str
    is_default: bool
    is_active: bool
