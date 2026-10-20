from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProfitabilityStockResponse(BaseModel):
    product_id: UUID
    product_name: str
    product_type: str
    unit_name: str
    unit_abbreviation: str
    quantity: Decimal
    valued_quantity: Decimal
    valued_cost: Decimal
    unvalued_quantity: Decimal


class ProfitabilityReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    farm_id: UUID
    from_date: date
    to_date: date
    accounting_basis: str = "accrual"
    inventory_cost_method: str = "moving_weighted_average"
    complete: bool
    incompleteness_reasons: list[str]
    gross_sales: Decimal
    sales_credits: Decimal
    net_revenue: Decimal
    cost_of_goods_sold: Decimal
    product_consumption_cost: Decimal
    egg_production_cost_allocated: Decimal
    unallocated_consumption_expense: Decimal
    operating_expenses: Decimal
    inventory_losses: Decimal
    net_profit: Decimal | None
    closing_stock_as_of: date
    closing_stock: list[ProfitabilityStockResponse]
    closing_stock_valued_cost: Decimal
    closing_stock_unvalued_quantity: Decimal
    untracked_chicken_quantity: Decimal
    untracked_egg_quantity: Decimal
    overrepresented_egg_quantity: Decimal
    customer_cash_refunds_excluded: Decimal
    supplier_cash_refunds_excluded: Decimal
    supplier_return_credits_excluded: Decimal


class ProfitabilityStockValuationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    unit_cost: Decimal = Field(ge=0, max_digits=14, decimal_places=6)


class ProfitabilityStockValuationResponse(BaseModel):
    product_id: UUID
    product_name: str
    unit_name: str
    unit_abbreviation: str
    valuation_date: date
    quantity_valued: Decimal
    unit_cost: Decimal
    inventory_movement_id: UUID
