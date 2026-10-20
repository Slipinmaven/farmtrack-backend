from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.schemas.enums import AgeUnit, ChickenType, PaymentMethod

NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]


class CashSettlementLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["cash"]
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    payment_method: PaymentMethod
    reference_number: str | None = Field(default=None, max_length=100)


class ChickenSettlementAllocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: UUID | None = None
    block_id: UUID
    quantity: int = Field(gt=0)


class NewChickenSettlementBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    chicken_type: ChickenType
    age: int = Field(ge=0)
    age_unit: AgeUnit

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class ChickenSettlementPlacement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["receive_existing", "receive_new", "issue"]
    batch_id: UUID | None = None
    new_batch: NewChickenSettlementBatch | None = None
    allocations: list[ChickenSettlementAllocation] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_mode(self) -> "ChickenSettlementPlacement":
        if self.mode == "receive_existing":
            if self.batch_id is None or self.new_batch is not None:
                raise ValueError("Choose one existing batch for received chickens.")
            if any(allocation.batch_id is not None for allocation in self.allocations):
                raise ValueError("Received chickens use one selected batch.")
        elif self.mode == "receive_new":
            if self.batch_id is not None or self.new_batch is None:
                raise ValueError("Provide the details for the new chicken batch.")
            if any(allocation.batch_id is not None for allocation in self.allocations):
                raise ValueError("A new batch cannot include existing batch allocations.")
        else:
            if self.batch_id is not None or self.new_batch is not None:
                raise ValueError("Chicken issues use a batch for each stock allocation.")
            if any(allocation.batch_id is None for allocation in self.allocations):
                raise ValueError("Choose a batch for every chicken stock allocation.")

        allocation_keys = [
            (allocation.batch_id, allocation.block_id)
            for allocation in self.allocations
        ]
        if len(allocation_keys) != len(set(allocation_keys)):
            raise ValueError("Each batch and block may appear only once.")
        return self


class GoodsSettlementLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["goods"]
    product_id: UUID
    unit_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    agreed_unit_value: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    chicken_placement: ChickenSettlementPlacement | None = None
    discount_type: Literal["fixed", "percentage"] | None = None
    discount_value: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=12, decimal_places=2)
    discount_reason: str | None = Field(default=None, max_length=200)

    @field_validator("discount_reason")
    @classmethod
    def normalize_discount_reason(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def validate_discount_terms(self) -> "GoodsSettlementLine":
        if self.discount_type is None and self.discount_value != 0:
            raise ValueError("Choose a discount type for the discount amount.")
        if self.discount_type == "percentage" and self.discount_value > 100:
            raise ValueError("A percentage discount cannot exceed 100%.")
        return self


class ChickenSettlementBatchOption(BaseModel):
    id: UUID
    name: str
    chicken_type: ChickenType
    hatch_date: date | None
    total_quantity: int


class ChickenSettlementBlockOption(BaseModel):
    id: UUID
    name: str
    current_chickens: int
    available_capacity: int
    batch_quantity: int | None = None


class ChickenSettlementOptionsResponse(BaseModel):
    batches: list[ChickenSettlementBatchOption] = Field(default_factory=list)
    blocks: list[ChickenSettlementBlockOption] = Field(default_factory=list)
    has_more: bool


class ServiceSettlementLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["service"]
    description: NonEmptyText
    value: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


SettlementLine = Annotated[
    CashSettlementLine | GoodsSettlementLine | ServiceSettlementLine,
    Field(discriminator="kind"),
]


class TransactionSettlementCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    direction: Literal["contact_to_farm", "farm_to_contact"]
    settlement_date: date
    reason: NonEmptyText
    notes: str | None = None
    lines: list[SettlementLine] = Field(min_length=1)


class TransactionSettlementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    transaction_id: UUID
    direction: Literal["contact_to_farm", "farm_to_contact"]
    settlement_date: date
    total_value: Decimal
    lines: list[dict[str, object]]
    reason: str
    notes: str | None
    created_at: datetime


class TransactionSettlementBalanceResponse(BaseModel):
    settlement: TransactionSettlementResponse
    amount_paid: Decimal
    balance_due: Decimal
    credit_balance: Decimal
