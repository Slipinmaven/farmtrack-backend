from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.schemas.enums import ProductType, TransactionStatus, TransactionType


class SalesReportProductSold(BaseModel):
    name: str
    quantity: Decimal
    unit_name: str | None


class SalesReportItem(BaseModel):
    id: UUID
    reference_number: str | None
    transaction_date: date
    status: TransactionStatus
    customer_name: str | None
    product_names: list[str]
    products_sold: list[SalesReportProductSold]
    categories: list[ProductType]
    transaction_total: Decimal
    amount_paid: Decimal
    balance_due: Decimal
    credit_balance: Decimal
    return_credits: Decimal
    goods_settlement: Decimal
    service_settlement: Decimal


class SalesReportMonth(BaseModel):
    month: str
    transaction_count: int
    sales_total: Decimal
    amount_received: Decimal
    balance_due: Decimal
    return_credits: Decimal
    goods_settlements: Decimal
    service_settlements: Decimal
    customer_credit: Decimal
    unallocated_amount: Decimal = Field(
        description="Legacy signed residual retained for API compatibility."
    )


class SalesReportDay(BaseModel):
    day: date
    transaction_count: int
    sales_total: Decimal


class SalesReportSummary(BaseModel):
    transaction_count: int
    sales_total: Decimal
    amount_received: Decimal = Field(
        description=(
            "Net transaction payments plus cash settlement lines for completed "
            "sales in the selected transaction-date, category, and search scope."
        )
    )
    balance_due: Decimal
    return_credits: Decimal = Field(
        description="Return credits applied against completed sales in this report scope."
    )
    goods_settlements: Decimal = Field(
        description=(
            "Signed goods settlement value applied to completed sales; positive is "
            "contact-to-farm, negative is farm-to-contact."
        )
    )
    service_settlements: Decimal = Field(
        description=(
            "Signed service settlement value applied to completed sales; positive is "
            "contact-to-farm, negative is farm-to-contact."
        )
    )
    customer_credit: Decimal = Field(
        description="Net overpayment/credit balance across completed sales in this scope."
    )
    unallocated_amount: Decimal = Field(
        description=(
            "Legacy signed residual retained for API compatibility; explained by "
            "return credits, goods and service settlements, and customer credit."
        )
    )
    monthly: list[SalesReportMonth]


class SalesReportResponse(BaseModel):
    items: list[SalesReportItem]
    sellable_categories: list[ProductType]
    total_count: int
    offset: int
    limit: int
    summary: SalesReportSummary
    daily: list[SalesReportDay] = Field(default_factory=list)


class PendingSaleDeliveryItem(BaseModel):
    product_name: str
    product_type: ProductType
    quantity_remaining: Decimal
    quantity_remaining_base: Decimal
    unit_name: str | None


class PendingSaleDelivery(BaseModel):
    id: UUID
    reference_number: str | None
    transaction_date: date
    customer_name: str | None
    items: list[PendingSaleDeliveryItem]


class OutstandingTransactionBalance(BaseModel):
    id: UUID
    transaction_type: TransactionType
    reference_number: str | None
    transaction_date: date
    contact_name: str | None
    balance_due: Decimal
    credit_balance: Decimal
    account_balance_due: Decimal
    account_credit_balance: Decimal


class OutstandingBalanceSummary(BaseModel):
    items: list[OutstandingTransactionBalance]
    customer_balance_due_total: Decimal
    supplier_balance_due_total: Decimal
    customer_credit_total: Decimal
    supplier_credit_total: Decimal


class SalesReportFilters(BaseModel):
    from_date: date | None = None
    to_date: date | None = None
    category: ProductType | None = None
    status: Literal["all", "completed", "cancelled"] = "completed"
    search: str | None = None

    @model_validator(mode="after")
    def validate_date_range(self) -> "SalesReportFilters":
        if (
            self.from_date is not None
            and self.to_date is not None
            and self.from_date > self.to_date
        ):
            raise ValueError("The start date must be on or before the end date.")
        return self
