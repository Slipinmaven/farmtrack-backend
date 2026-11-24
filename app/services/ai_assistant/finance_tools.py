import re
from decimal import Decimal
from typing import Any

from app.core.exceptions import AppError
from app.services.ai_assistant.contracts import (
    ContactBalancesToolArguments,
    ContactLedgerToolArguments,
    DateRangeToolArguments,
    ExpenseHistoryToolArguments,
    ExpenseSummaryToolArguments,
)
from app.services.ai_assistant.date_ranges import resolve_tool_date_range
from app.services.ai_assistant.service_context import AssistantToolHandlerBase


class FinanceToolHandlers(AssistantToolHandlerBase):
    async def _handle_get_contact_balances(self, arguments: dict[str, Any]) -> dict[str, Any]:
        parsed = ContactBalancesToolArguments.model_validate(arguments)
        ledger = await self._get_ledger_summary()
        result = self.context.service._safe_contact_balances(
            ledger,
            contact_name=parsed.contact_name,
        )
        self.context.data_scopes.append("contact_balances")
        return result

    async def _handle_get_contact_ledger(self, arguments: dict[str, Any]) -> dict[str, Any]:
        parsed = ContactLedgerToolArguments.model_validate(arguments)
        from_date, to_date = resolve_tool_date_range(
            parsed,
            self.context.question,
            default_period="full_history",
        )
        self.context.ledger_summary = await self._get_ledger_summary()
        matches = self.context.service._matching_accounts(
            self.context.ledger_summary,
            parsed.contact_name,
        )
        if len(matches) != 1:
            self.context.data_scopes.append("contact_balances")
            return self.context.service._safe_contact_balances(
                self.context.ledger_summary,
                contact_name=parsed.contact_name,
            )

        account = matches[0]
        if account.contact_id is None:
            return {"match_status": "not_found", "accounts": []}
        account_ledger_service = self.context.service.account_ledger_service
        if account_ledger_service is None:
            raise AppError(
                "AI_ASSISTANT_UNAVAILABLE",
                "The assistant's read tools are not configured.",
                503,
            )
        ledger = await account_ledger_service.get_ledger(
            self.context.farm_id,
            contact_id=account.contact_id,
            from_date=from_date,
            to_date=to_date,
        )
        self.context.used_from_date = from_date
        self.context.used_to_date = to_date
        self.context.data_scopes.append("contact_ledger")
        all_events = ledger.events
        events = all_events[-100:]
        return {
            "contact_name": self.context.service._safe_contact_name(
                account.contact_name
            ),
            "roles": account.roles,
            "current_balance": format(account.balance, "f"),
            "balance_status": self.context.service._balance_status(
                account.balance,
                account.roles,
            ),
            "from_date": (
                from_date.isoformat() if from_date is not None else None
            ),
            "to_date": to_date.isoformat() if to_date is not None else None,
            "opening_balance": format(
                ledger.opening_balance or Decimal("0.00"),
                "f",
            ),
            "closing_balance": format(
                ledger.closing_balance or Decimal("0.00"),
                "f",
            ),
            "event_count": len(all_events),
            "events_truncated": len(all_events) > len(events),
            "events": [
                {
                    "date": event.event_date.isoformat(),
                    "transaction_type": event.transaction_type,
                    "event_type": event.event_type,
                    "description": self.context.service._safe_ledger_event_description(
                        event
                    ),
                    "amount": format(event.amount, "f"),
                    "running_balance": format(
                        event.running_balance,
                        "f",
                    ),
                    "settlement_components": self.context.service._safe_settlement_components(
                        event
                    ),
                    "href": (
                        f"/transactions/{event.transaction_id}/settlements"
                        if event.transaction_type == "purchase"
                        else f"/sales/{event.transaction_id}"
                    ),
                }
                for event in events
            ],
            "balance_sign_guide": (
                "Use balance_status for direction. Event amounts and "
                "running_balance are signed; later events may settle, "
                "overpay, or reverse an earlier balance."
            ),
        }

    async def _handle_get_expense_history(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.context.farm is None or self.context.service.expense_service is None:
            raise AppError(
                "AI_ASSISTANT_UNAVAILABLE",
                "Expense history capability is not configured.",
                503,
            )
        parsed = ExpenseHistoryToolArguments.model_validate(arguments)
        from_date, to_date = self.context.service._resolve_expense_history_dates(
            parsed,
            self.context.question,
            self.context.previous_expense_period,
        )
        report = await self.context.service.expense_service.list_expenses(
            self.context.farm,
            category=parsed.category,
            from_date=from_date,
            to_date=to_date,
            search=parsed.search,
            payment_status=(
                "cancelled" if parsed.status == "cancelled" else None
            ),
            exclude_cancelled=parsed.status == "active",
            exclude_purchase_linked=(
                parsed.operating_expenses_only
                or (
                    self.context.previous_report_is_profitability
                    and self.context.service._is_expense_detail_follow_up(self.context.question)
                )
            ),
            offset=parsed.offset,
            limit=parsed.limit,
        )
        self.context.used_from_date = from_date
        self.context.used_to_date = to_date
        self.context.data_scopes.append("expense_history")
        return {
            "farm_name": self.context.service._safe_contact_name(self.context.farm.name),
            "period": {
                "from_date": (
                    from_date.isoformat() if from_date is not None else None
                ),
                "to_date": (
                    to_date.isoformat() if to_date is not None else None
                ),
            },
            "total_count": report.total_count,
            "offset": report.offset,
            "limit": report.limit,
            "has_more": (
                report.offset + len(report.items) < report.total_count
            ),
            "record_scope": (
                "operating expenses"
                if parsed.operating_expenses_only
                or (
                    self.context.previous_report_is_profitability
                    and self.context.service._is_expense_detail_follow_up(self.context.question)
                )
                else f"{parsed.status} expenses"
            ),
            "expenses": [
                {
                    "name": self.context.service._safe_contact_name(item.name),
                    "category": self.context.service._safe_contact_name(
                        item.category_name
                    ),
                    "date": item.expense_date.isoformat(),
                    "amount": format(item.amount, "f"),
                    "amount_paid": format(item.amount_paid, "f"),
                    "balance_due": format(item.balance_due, "f"),
                    "payment_status": getattr(
                        item.payment_status,
                        "value",
                        item.payment_status,
                    ),
                    "is_purchase_linked": (
                        item.purchase_transaction_id is not None
                    ),
                    "block_name": (
                        self.context.service._safe_contact_name(item.block_name)
                        if item.block_name
                        else None
                    ),
                    "href": f"/expenses/{item.id}",
                }
                for item in report.items
            ],
        }

    async def _handle_get_expense_summary(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.context.farm is None or self.context.service.expense_service is None:
            raise AppError(
                "AI_ASSISTANT_UNAVAILABLE",
                "Expense reporting capability is not configured.",
                503,
            )
        parsed = ExpenseSummaryToolArguments.model_validate(arguments)
        count_question = bool(
            re.search(
                r"\b(how many|number of|count|all[- ]time|ever|"
                r"what expenses do i have)\b",
                self.context.question,
                re.IGNORECASE,
            )
        )
        from_date, to_date = resolve_tool_date_range(
            parsed,
            self.context.question,
            default_period=(
                "full_history" if count_question else "month_to_date"
            ),
        )
        report = await self.context.service.expense_service.get_expense_summary(
            self.context.farm,
            from_date=from_date,
            to_date=to_date,
        )
        categories = report.categories
        if parsed.category:
            categories = [
                item
                for item in categories
                if parsed.category.casefold()
                in {item.key.casefold(), item.name.casefold()}
            ]
            if not categories:
                return {
                    "match_status": "category_not_found",
                    "requested_category": parsed.category,
                    "available_categories": [
                        item.name for item in report.categories[:50]
                    ],
                }
        self.context.data_scopes.append("expense_summary")
        self.context.used_from_date = from_date
        self.context.used_to_date = to_date
        return {
            "farm_name": self.context.service._safe_contact_name(self.context.farm.name),
            "period": {
                "from_date": (
                    from_date.isoformat() if from_date is not None else None
                ),
                "to_date": (
                    to_date.isoformat() if to_date is not None else None
                ),
            },
            "record_scope": "active expenses",
            "calculation_basis": (
                "Active expense records in this period, including "
                "purchase-linked expenses; cancelled records excluded. "
                "Total amount is the sum of recorded expense amounts. "
                "Amount paid is net payments minus refunds, capped at "
                "each expense amount and floored at zero; balance due is "
                "the remaining amount."
            ),
            "filtered_by_category": parsed.category,
            "expense_count": sum(
                category.expense_count for category in categories
            ),
            "total_amount": format(
                sum(
                    (category.total_amount for category in categories),
                    Decimal("0"),
                ),
                "f",
            ),
            "amount_paid": format(
                sum(
                    (category.amount_paid for category in categories),
                    Decimal("0"),
                ),
                "f",
            ),
            "balance_due": format(
                sum(
                    (category.balance_due for category in categories),
                    Decimal("0"),
                ),
                "f",
            ),
            "categories": [
                {
                    "name": item.name,
                    "expense_count": item.expense_count,
                    "total_amount": format(item.total_amount, "f"),
                    "amount_paid": format(item.amount_paid, "f"),
                    "balance_due": format(item.balance_due, "f"),
                }
                for item in categories
            ],
        }

    async def _handle_get_profitability_report(self, arguments: dict[str, Any]) -> dict[str, Any]:
        parsed = DateRangeToolArguments.model_validate(arguments)
        from_date, to_date = resolve_tool_date_range(
            parsed,
            self.context.question,
            default_period="month_to_date",
        )
        if from_date is None or to_date is None:
            raise AppError(
                "AI_ASSISTANT_INVALID_DATE_RANGE",
                "A date range could not be resolved.",
                422,
            )
        report = await self.context.service.profitability_service.build_report(
            self.context.farm_id,
            from_date=from_date,
            to_date=to_date,
        )
        self.context.used_from_date = from_date
        self.context.used_to_date = to_date
        self.context.data_scopes.append("profitability_report")
        return self.context.service._safe_report_context(report)
