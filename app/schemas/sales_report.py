from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.schemas.enums import ProductType, TransactionStatus


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


class SalesReportMonth(BaseModel):
    month: str
    transaction_count: int
    sales_total: Decimal
    amount_received: Decimal


class SalesReportDay(BaseModel):
    day: date
    transaction_count: int
    sales_total: Decimal


class SalesReportSummary(BaseModel):
    transaction_count: int
    sales_total: Decimal
    amount_received: Decimal
    balance_due: Decimal
    monthly: list[SalesReportMonth]


class SalesReportResponse(BaseModel):
    items: list[SalesReportItem]
    sellable_categories: list[ProductType]
    total_count: int
    offset: int
    limit: int
    summary: SalesReportSummary
    daily: list[SalesReportDay] = Field(default_factory=list)


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
