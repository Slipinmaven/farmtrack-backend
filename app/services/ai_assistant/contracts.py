from datetime import date, datetime, time
from typing import Any, Awaitable, Callable, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.assistant_conversation import AssistantConversation, AssistantMessage
from app.models.farm import Farm
from app.schemas.account_ledger import AccountLedgerResponse
from app.schemas.block import BlockResponse
from app.schemas.chicken_loss import ChickenLossResponse
from app.schemas.chicken_movement import ChickenMovementResponse
from app.schemas.egg_collection import EggCollectionResponse
from app.schemas.egg_loss import EggLossResponse
from app.schemas.expense import ExpenseSummaryResponse
from app.schemas.inventory import InventoryProductBalance
from app.schemas.product import ProductResponse
from app.schemas.product_consumption import ProductConsumptionResponse
from app.schemas.profitability_report import ProfitabilityReportResponse
from app.schemas.receipt_history import ReceiptHistoryFilters, ReceiptHistoryResponse
from app.schemas.sales_report import PendingSaleDelivery, SalesReportFilters, SalesReportResponse

class DateRangeToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_date: date | None = None
    to_date: date | None = None

    @model_validator(mode="after")
    def validate_period(self) -> "DateRangeToolArguments":
        if (
            self.from_date is not None
            and self.to_date is not None
            and self.from_date > self.to_date
        ):
            raise ValueError("from_date must be on or before to_date.")
        if (
            self.from_date is not None
            and self.to_date is not None
            and (self.to_date - self.from_date).days > 366
        ):
            raise ValueError("The period must not exceed 367 days.")
        return self

class SalesReportToolArguments(DateRangeToolArguments):
    from_time: time | None = None
    to_time: time | None = None

    @model_validator(mode="after")
    def validate_time_range(self) -> "SalesReportToolArguments":
        if (self.from_time is None) != (self.to_time is None):
            raise ValueError("from_time and to_time must be provided together.")
        if (
            self.from_date == self.to_date
            and self.from_time is not None
            and self.to_time is not None
            and self.from_time >= self.to_time
        ):
            raise ValueError("from_time must be before to_time.")
        return self

class PurchaseHistoryToolArguments(DateRangeToolArguments):
    search: str | None = Field(default=None, min_length=1, max_length=150)
    offset: int = Field(default=0, ge=0, le=100_000)
    limit: int = Field(default=50, ge=1, le=100)

    @field_validator("search")
    @classmethod
    def strip_search(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("search cannot be blank.")
        return normalized

class SalesHistoryToolArguments(DateRangeToolArguments):
    offset: int = Field(default=0, ge=0, le=100_000)
    limit: int = Field(default=50, ge=1, le=100)

class TransactionDetailsToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: UUID
    transaction_type: Literal["sale", "purchase"]

class ExpenseSummaryToolArguments(DateRangeToolArguments):
    category: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("category")
    @classmethod
    def strip_category(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("category cannot be blank.")
        return normalized

class ExpenseHistoryToolArguments(DateRangeToolArguments):
    category: str | None = Field(default=None, min_length=1, max_length=100)
    search: str | None = Field(default=None, min_length=1, max_length=150)
    status: Literal["active", "cancelled", "all"] = "active"
    operating_expenses_only: bool = False
    offset: int = Field(default=0, ge=0, le=100_000)
    limit: int = Field(default=50, ge=1, le=100)

    @field_validator("category", "search")
    @classmethod
    def strip_filter(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Filter cannot be blank.")
        return normalized

class FarmOperationsSummaryToolArguments(DateRangeToolArguments):
    block_name: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("block_name")
    @classmethod
    def strip_block_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("block_name cannot be blank.")
        return normalized

class BlockStatusToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_name: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("block_name")
    @classmethod
    def strip_block_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("block_name cannot be blank.")
        return normalized

class ContactBalancesToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contact_name: str | None = Field(default=None, min_length=1, max_length=150)

class InventoryBalancesToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_name: str | None = Field(default=None, min_length=1, max_length=150)

class ContactLedgerToolArguments(DateRangeToolArguments):
    contact_name: str = Field(min_length=1, max_length=150)

class ClarificationToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=500)

class AppNavigationToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    destination: str = Field(min_length=1, max_length=50)

AssistantToolExecutor = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]

class AccountLedgerReader(Protocol):
    async def get_ledger(
        self,
        farm_id: UUID,
        *,
        contact_id: UUID | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> AccountLedgerResponse: ...

class InventoryBalanceReader(Protocol):
    async def get_balances(
        self,
        farm_id: UUID,
    ) -> list[InventoryProductBalance]: ...

class FarmOperationsBlockReader(Protocol):
    async def list_blocks(
        self,
        farm: Farm,
        search: str | None = None,
        is_active: bool | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[BlockResponse]: ...

class FarmOperationsProductReader(Protocol):
    async def list_products(
        self,
        farm: Farm,
        search: str | None = None,
    ) -> list[ProductResponse]: ...

class ChickenLossReader(Protocol):
    async def list_losses(
        self,
        farm: Farm,
        *,
        batch_id: UUID | None = None,
        block_id: UUID | None = None,
        reason: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[ChickenLossResponse]: ...

class ChickenMovementReader(Protocol):
    async def list_movements(
        self,
        farm: Farm,
        *,
        batch_id: UUID | None = None,
        from_block_id: UUID | None = None,
        to_block_id: UUID | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[ChickenMovementResponse]: ...

class EggCollectionReader(Protocol):
    async def list_collections(
        self,
        farm: Farm,
        *,
        product_id: UUID | None = None,
        block_id: UUID | None = None,
        from_datetime: datetime | None = None,
        to_datetime: datetime | None = None,
    ) -> list[EggCollectionResponse]: ...

class EggLossReader(Protocol):
    async def list_losses(
        self,
        farm: Farm,
        *,
        product_id: UUID | None = None,
        reason: Any = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[EggLossResponse]: ...

class ProductConsumptionReader(Protocol):
    async def list_consumptions(
        self,
        farm: Farm,
        *,
        product_id: UUID | None = None,
        block_id: UUID | None = None,
        batch_id: UUID | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[ProductConsumptionResponse]: ...

class AssistantProvider(Protocol):
    async def answer(
        self,
        *,
        question: str,
        report_context: dict[str, Any],
        conversation_history: list[dict[str, str]] | None = None,
    ) -> str: ...

    async def answer_with_tools(
        self,
        *,
        question: str,
        conversation_history: list[dict[str, str]],
        execute_tool: AssistantToolExecutor,
    ) -> tuple[str, bool]: ...

class ProfitabilityReportReader(Protocol):
    async def build_report(
        self,
        farm_id: UUID,
        *,
        from_date: date,
        to_date: date,
    ) -> ProfitabilityReportResponse: ...

class SalesReportReader(Protocol):
    async def get_report(
        self,
        farm_id: UUID,
        filters: SalesReportFilters,
        offset: int,
        limit: int,
        include_daily: bool = False,
    ) -> SalesReportResponse: ...

    async def get_pending_deliveries(
        self,
        farm_id: UUID,
        *,
        limit: int,
    ) -> list[PendingSaleDelivery]: ...

class PurchaseHistoryReader(Protocol):
    async def get_history(
        self,
        farm_id: UUID,
        filters: ReceiptHistoryFilters,
        offset: int,
        limit: int,
    ) -> ReceiptHistoryResponse: ...

class ExpenseReader(Protocol):
    async def get_expense_summary(
        self,
        farm: Farm,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> ExpenseSummaryResponse: ...

    async def list_expenses(
        self,
        farm: Farm,
        *,
        category: str | None = None,
        contact_id: UUID | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        search: str | None = None,
        payment_status: str | None = None,
        block_id: UUID | None = None,
        exclude_cancelled: bool = False,
        exclude_purchase_linked: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> Any: ...

class TransactionRepositoryReader(Protocol):
    async def get_sale_detail_by_id(
        self,
        farm_id: UUID,
        transaction_id: UUID,
    ) -> Any | None: ...

    async def get_purchase_detail_by_id(
        self,
        farm_id: UUID,
        transaction_id: UUID,
    ) -> Any | None: ...

class SaleDeliveryReader(Protocol):
    async def list_deliveries(
        self,
        farm_id: UUID,
        transaction_id: UUID,
    ) -> list[Any]: ...

class TransactionRefundReader(Protocol):
    async def list_refunds(
        self,
        farm_id: UUID,
        transaction_id: UUID,
    ) -> list[Any]: ...

class PurchaseReturnReader(Protocol):
    async def list_returns(
        self,
        farm_id: UUID,
        transaction_id: UUID,
    ) -> list[Any]: ...

class PurchaseReplacementReader(Protocol):
    async def list_replacements(
        self,
        farm_id: UUID,
        transaction_id: UUID,
    ) -> list[Any]: ...

class PurchaseSupplierRefundReader(Protocol):
    async def list_refunds(
        self,
        farm_id: UUID,
        transaction_id: UUID,
    ) -> list[Any]: ...

class SaleReturnReader(Protocol):
    async def list_returns(
        self,
        farm_id: UUID,
        transaction_id: UUID,
    ) -> list[Any]: ...

class ChickenPurchaseDetailsReader(Protocol):
    async def get_details(
        self,
        farm_id: UUID,
        transaction_id: UUID,
    ) -> Any: ...

class AssistantConversationStore(Protocol):
    async def create(
        self,
        *,
        farm_id: UUID,
        user_id: UUID,
        title: str,
    ) -> AssistantConversation: ...

    async def get_for_user(
        self,
        *,
        conversation_id: UUID,
        farm_id: UUID,
        user_id: UUID,
    ) -> AssistantConversation | None: ...

    async def list_for_user(
        self,
        *,
        farm_id: UUID,
        user_id: UUID,
        limit: int,
        offset: int,
    ) -> list[AssistantConversation]: ...

    async def list_messages(
        self,
        conversation_id: UUID,
    ) -> list[AssistantMessage]: ...

    async def add_exchange(
        self,
        *,
        conversation: AssistantConversation,
        question: str,
        answer: str,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> None: ...

    async def delete(self, conversation: AssistantConversation) -> None: ...

class Committer(Protocol):
    async def commit(self) -> None: ...
