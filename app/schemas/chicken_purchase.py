from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.schemas.enums import AgeUnit, ChickenType
from app.schemas.contact import ContactResponse
from app.schemas.payment import PaymentCreate, PaymentResponse
from app.schemas.product import ProductResponse
from app.schemas.transaction import TransactionResponse

PositiveQuantity = Annotated[int, Field(gt=0)]
NonEmptyString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]


class ChickenPurchaseItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    chicken_type: ChickenType
    quantity: PositiveQuantity
    unit_id: UUID
    unit_price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    notes: str | None = None


class ChickenPurchaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_date: date | None = None
    notes: str | None = None
    supplier_id: UUID | None = None
    items: list[ChickenPurchaseItemCreate] = Field(min_length=1)
    payments: list[PaymentCreate] = Field(default_factory=list)
    discount_type: Literal["fixed", "percentage"] | None = None
    discount_value: Decimal = Field(
        default=Decimal("0.00"), ge=0, max_digits=12, decimal_places=2
    )
    discount_reason: str | None = Field(default=None, max_length=200)
    overpayment_confirmed: bool = False

    @model_validator(mode="after")
    def validate_discount_terms(self) -> ChickenPurchaseRequest:
        if self.discount_type is None and self.discount_value != Decimal("0.00"):
            raise ValueError("Choose a discount type for the discount amount.")
        if (
            self.discount_type == "percentage"
            and self.discount_value > Decimal("100.00")
        ):
            raise ValueError("A percentage discount cannot exceed 100%.")
        return self


class BlockAllocationRequest(BaseModel):
    block_id: UUID
    quantity: PositiveQuantity


class NewChickenBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: NonEmptyString | None = None
    chicken_type: ChickenType
    breed: str | None = Field(default=None, max_length=100)
    age: int | None = Field(default=None, ge=0)
    age_unit: AgeUnit | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def validate_age_pair(self) -> NewChickenBatchRequest:
        if (self.age is None) != (self.age_unit is None):
            raise ValueError("age and age_unit must either both be provided or both omitted.")
        return self


class CreateBatchAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["CREATE"]
    new_batch: NewChickenBatchRequest


class ExistingBatchAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["USE_EXISTING"]
    batch_id: UUID


BatchAssignment = Annotated[
    CreateBatchAssignment | ExistingBatchAssignment,
    Field(discriminator="action"),
]


class ChickenReceiptItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_item_id: UUID
    quantity_received: PositiveQuantity
    batch_assignment: BatchAssignment | None = None
    block_allocations: list[BlockAllocationRequest] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_allocations(self) -> ChickenReceiptItemRequest:
        block_ids = [allocation.block_id for allocation in self.block_allocations]
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("Each block may appear only once per receipt item.")
        if sum(allocation.quantity for allocation in self.block_allocations) != self.quantity_received:
            raise ValueError("Block allocations must equal quantity_received.")
        return self


class PurchaseReceiptCreateRequest(BaseModel):
    transaction_id: UUID
    received_date: date
    received_time: time | None = None
    notes: str | None = None
    items: list[ChickenReceiptItemRequest] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_transaction_items(self) -> PurchaseReceiptCreateRequest:
        item_ids = [item.transaction_item_id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("Each purchase item may appear only once per receipt.")
        return self


class BlockAllocationResponse(BaseModel):
    block_id: UUID
    quantity: int
    block_name: str | None = None


class PurchaseReceiptItemResponse(BaseModel):
    id: UUID
    transaction_item_id: UUID
    quantity_received: Decimal
    batch_id: UUID | None
    batch_name: str | None
    hatch_date: date | None
    remaining_quantity: Decimal
    block_allocations: list[BlockAllocationResponse]


class PurchaseReceiptResponse(BaseModel):
    id: UUID
    transaction_id: UUID
    received_date: date
    received_time: time | None
    notes: str | None
    created_at: datetime
    items: list[PurchaseReceiptItemResponse]


class ChickenPurchaseResponse(TransactionResponse):
    pass


class PurchaseOutstandingBalanceResponse(BaseModel):
    id: UUID
    reference_number: str | None
    transaction_date: date
    transaction_total: Decimal
    amount_paid: Decimal
    balance_due: Decimal
    credit_balance: Decimal


class ChickenPurchaseDetailResponse(BaseModel):
    transaction: ChickenPurchaseResponse
    supplier_name: str | None
    receipts: list[PurchaseReceiptResponse]
    outstanding_supplier_balances: list[PurchaseOutstandingBalanceResponse]
    supplier_balance_total: Decimal
    supplier_credit_total: Decimal


class ChickenPurchaseBlockOption(BaseModel):
    id: UUID
    name: str
    capacity: int
    over_capacity_limit: int
    maximum_chickens: int
    current_chickens: int
    available_capacity: int


class ChickenPurchaseBatchOption(BaseModel):
    id: UUID
    name: str
    chicken_type: ChickenType
    hatch_date: date | None


class ChickenPurchaseOptionsResponse(BaseModel):
    products: list[ProductResponse]
    suppliers: list[ContactResponse]
    blocks: list[ChickenPurchaseBlockOption]
    batches: list[ChickenPurchaseBatchOption]