from typing import Any

from pydantic import ValidationError

from app.services.ai_assistant.farm_tools import FarmToolHandlers
from app.services.ai_assistant.finance_tools import FinanceToolHandlers
from app.services.ai_assistant.operations_tools import OperationsToolHandlers
from app.services.ai_assistant.sales_tools import SalesToolHandlers
from app.services.ai_assistant.service_context import (
    AssistantToolExecutionContext,
)


class ChatToolExecutor(
    FarmToolHandlers,
    FinanceToolHandlers,
    SalesToolHandlers,
    OperationsToolHandlers,
):
    def __init__(self, context: AssistantToolExecutionContext) -> None:
        super().__init__(context)

    async def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            if name == "get_current_farm":
                return await self._handle_get_current_farm(arguments)
            if name == "get_profitability_report":
                return await self._handle_get_profitability_report(arguments)
            if name == "get_contact_balances":
                return await self._handle_get_contact_balances(arguments)
            if name == "get_contact_ledger":
                return await self._handle_get_contact_ledger(arguments)
            if name == "get_sales_report":
                return await self._handle_get_sales_report(arguments)
            if name == "get_sales_history":
                return await self._handle_get_sales_history(arguments)
            if name == "get_purchase_history":
                return await self._handle_get_purchase_history(arguments)
            if name == "get_transaction_details":
                return await self._handle_get_transaction_details(arguments)
            if name == "get_expense_summary":
                return await self._handle_get_expense_summary(arguments)
            if name == "get_expense_history":
                return await self._handle_get_expense_history(arguments)
            if name == "get_app_navigation":
                return await self._handle_get_app_navigation(arguments)
            if name == "get_app_route_catalog":
                return await self._handle_get_app_route_catalog(arguments)
            if name == "get_farm_block_status":
                return await self._handle_get_farm_block_status(arguments)
            if name == "get_pending_deliveries":
                return await self._handle_get_pending_deliveries(arguments)
            if name == "get_inventory_balances":
                return await self._handle_get_inventory_balances(arguments)
            if name == "get_farm_operations_summary":
                return await self._handle_get_farm_operations_summary(arguments)
            return {"error": "Unsupported read capability."}
        except ValidationError:
            return {
                "error": (
                    "Invalid tool arguments. Ask the user for the missing or "
                    "valid contact name and date range."
                )
            }
