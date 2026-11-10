from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class ProfitabilityProductResponse(BaseModel):
    product_id: UUID
    product_name: str
    product_type: str
    unit_name: str
    unit_abbreviation: str
    quantity_sold: Decimal
    sales_value: Decimal
    sales_credits: Decimal
    net_sales: Decimal
    cost_of_goods_sold: Decimal
    average_selling_price: Decimal | None
    average_unit_cost: Decimal | None
    gross_profit: Decimal | None
    uncosted_quantity: Decimal
    uncosted_movement_quantity: Decimal = Decimal("0")
    uncosted_movement_types: list[str] = Field(default_factory=list)
    estimated_cost_used: bool = False


class EggStockReconciliationResponse(BaseModel):
    product_id: UUID
    product_name: str
    unit_name: str
    unit_abbreviation: str
    supported_quantity: Decimal
    ledger_quantity: Decimal
    difference: Decimal


class ReservedEggSaleResponse(BaseModel):
    transaction_id: UUID
    reference_number: str | None
    transaction_date: date
    product_id: UUID
    product_name: str
    unit_abbreviation: str
    reserved_quantity: Decimal


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
    egg_production_zero_cost_confirmed: bool = False
    egg_production_zero_cost_confirmation_available: bool = False
    unallocated_consumption_expense: Decimal
    operating_expenses: Decimal
    inventory_losses: Decimal
    net_profit: Decimal | None
    closing_stock_as_of: date
    closing_stock: list[ProfitabilityStockResponse]
    product_performance: list[ProfitabilityProductResponse]
    egg_stock_reconciliation: list[EggStockReconciliationResponse] = Field(
        default_factory=list
    )
    reserved_egg_sales: list[ReservedEggSaleResponse] = Field(default_factory=list)
    unvalued_period_movement_count: int = 0
    missing_inventory_record_count: int = 0
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
    from_date: date | None = None
    to_date: date | None = None

    @model_validator(mode="after")
    def validate_period(self) -> "ProfitabilityStockValuationRequest":
        if (self.from_date is None) != (self.to_date is None):
            raise ValueError("Both report period dates must be provided together.")
        if (
            self.from_date is not None
            and self.to_date is not None
            and self.from_date > self.to_date
        ):
            raise ValueError("Report start date must be on or before its end date.")
        return self


class ProfitabilityStockValuationResponse(BaseModel):
    product_id: UUID
    product_name: str
    unit_name: str
    unit_abbreviation: str
    valuation_date: date
    quantity_valued: Decimal
    unit_cost: Decimal
    inventory_movement_id: UUID


class EggProductionCostConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_date: date
    to_date: date

    @model_validator(mode="after")
    def validate_period(self) -> "EggProductionCostConfirmationRequest":
        if self.from_date > self.to_date:
            raise ValueError("Report start date must be on or before its end date.")
        return self


class EggProductionCostConfirmationResponse(BaseModel):
    confirmed: bool
    from_date: date
    to_date: date
