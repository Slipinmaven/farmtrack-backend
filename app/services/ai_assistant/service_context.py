from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, ClassVar, Literal, Protocol
from uuid import UUID

from app.core.exceptions import AppError
from app.models.farm import Farm
from app.schemas.account_ledger import AccountLedgerResponse
from app.schemas.profitability_report import ProfitabilityReportResponse
from app.services.ai_assistant.contracts import (
    AccountLedgerReader,
    AssistantConversationStore,
    AssistantProvider,
    ChickenLossReader,
    ChickenMovementReader,
    ChickenPurchaseDetailsReader,
    Committer,
    EggCollectionReader,
    EggLossReader,
    ExpenseReader,
    FarmOperationsBlockReader,
    FarmOperationsProductReader,
    InventoryBalanceReader,
    ProductConsumptionReader,
    ProfitabilityReportReader,
    PurchaseHistoryReader,
    PurchaseReplacementReader,
    PurchaseReturnReader,
    PurchaseSupplierRefundReader,
    SaleDeliveryReader,
    SaleReturnReader,
    SalesReportReader,
    TransactionRefundReader,
    TransactionRepositoryReader,
)


class AssistantServiceContext(Protocol):
    APP_DESTINATIONS: ClassVar[dict[str, dict[str, str]]]
    profitability_service: ProfitabilityReportReader
    account_ledger_service: AccountLedgerReader | None
    inventory_service: InventoryBalanceReader | None
    sales_report_service: SalesReportReader | None
    purchase_history_service: PurchaseHistoryReader | None
    transaction_repository: TransactionRepositoryReader | None
    sale_delivery_service: SaleDeliveryReader | None
    chicken_purchase_details_service: ChickenPurchaseDetailsReader | None
    transaction_refund_service: TransactionRefundReader | None
    purchase_return_service: PurchaseReturnReader | None
    purchase_replacement_service: PurchaseReplacementReader | None
    purchase_supplier_refund_service: PurchaseSupplierRefundReader | None
    sale_return_service: SaleReturnReader | None
    expense_service: ExpenseReader | None
    block_service: FarmOperationsBlockReader | None
    product_service: FarmOperationsProductReader | None
    chicken_loss_service: ChickenLossReader | None
    chicken_movement_service: ChickenMovementReader | None
    egg_collection_service: EggCollectionReader | None
    egg_loss_service: EggLossReader | None
    product_consumption_service: ProductConsumptionReader | None
    conversation_repository: AssistantConversationStore
    unit_of_work: Committer
    provider_manager: AssistantProvider

    @staticmethod
    def _safe_contact_name(name: str) -> str: ...

    @staticmethod
    def _safe_report_context(
        report: ProfitabilityReportResponse,
    ) -> dict[str, Any]: ...

    @classmethod
    def _safe_contact_balances(
        cls,
        ledger: AccountLedgerResponse,
        *,
        contact_name: str | None,
    ) -> dict[str, Any]: ...

    @staticmethod
    def _matching_accounts(
        ledger: AccountLedgerResponse,
        contact_name: str,
    ) -> list[Any]: ...

    @staticmethod
    def _balance_status(balance: Decimal, roles: list[str]) -> str: ...

    @classmethod
    def _safe_ledger_event_description(cls, event: Any) -> str: ...

    @staticmethod
    def _safe_settlement_components(event: Any) -> dict[str, str]: ...

    @classmethod
    def _collect_assistant_hrefs(cls, value: Any) -> set[str]: ...

    @staticmethod
    def _remove_unverified_assistant_links(
        answer: str,
        verified_hrefs: set[str],
    ) -> str: ...

    @staticmethod
    def _add_source_route_context(
        question: str,
        source_route: str | None,
    ) -> str: ...

    @staticmethod
    def _is_expense_detail_follow_up(question: str) -> bool: ...

    @classmethod
    def _resolve_expense_history_dates(
        cls,
        arguments: Any,
        question: str,
        previous_expense_period: tuple[date, date] | None,
    ) -> tuple[date | None, date | None]: ...

    async def _farm_operations_summary(
        self,
        farm: Farm,
        parsed: Any,
    ) -> dict[str, Any]: ...

    async def _read_transaction_details(
        self,
        *,
        farm: Farm,
        transaction_id: UUID,
        transaction_type: Literal["sale", "purchase"],
    ) -> dict[str, Any] | None: ...


@dataclass
class AssistantToolExecutionContext:
    service: AssistantServiceContext
    farm: Farm | None
    farm_id: UUID
    question: str
    previous_expense_period: tuple[date, date] | None
    previous_report_is_profitability: bool
    data_scopes: list[str]
    used_from_date: date | None = None
    used_to_date: date | None = None
    navigation_destination: str | None = None
    ledger_summary: AccountLedgerResponse | None = None


class AssistantToolHandlerBase:
    context: AssistantToolExecutionContext

    def __init__(self, context: AssistantToolExecutionContext) -> None:
        self.context = context

    async def _get_ledger_summary(self) -> AccountLedgerResponse:
        ledger = self.context.ledger_summary
        if ledger is None:
            account_ledger_service = self.context.service.account_ledger_service
            if account_ledger_service is None:
                raise AppError(
                    "AI_ASSISTANT_UNAVAILABLE",
                    "The assistant's read tools are not configured.",
                    503,
                )
            ledger = await account_ledger_service.get_ledger(self.context.farm_id)
            self.context.ledger_summary = ledger
        return ledger
