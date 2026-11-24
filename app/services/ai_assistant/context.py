import re
from datetime import date
from decimal import Decimal
from typing import Any

from app.schemas.account_ledger import AccountLedgerResponse
from app.schemas.profitability_report import ProfitabilityReportResponse
from app.services.assistant_route_catalog import describe_app_route, resolve_app_route
from app.services.ai_assistant.contracts import ExpenseHistoryToolArguments
from app.services.ai_assistant.date_ranges import resolve_tool_date_range
from app.services.ai_assistant.service_context import AssistantServiceContext

_CONTACT_EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_CONTACT_PHONE_PATTERN = re.compile(
    r"(?<!\w)(?:\+\d{8,15}|0\d{9,14}|"
    r"\d{3,5}[ .()-]\d{3,5}[ .()-]\d{3,5})(?!\w)"
)

class FarmAssistantContextMixin(AssistantServiceContext):
    @staticmethod
    def _add_source_route_context(
        question: str,
        source_route: str | None,
    ) -> str:
        if source_route is None:
            return question
        route = resolve_app_route(source_route)
        if route is None:
            return question
        context = describe_app_route(route)
        return f"[FarmTrack app context: {context}]\n{question}"

    @staticmethod
    def _is_expense_detail_follow_up(question: str) -> bool:
        return bool(
            re.search(
                r"\b(which|what|show|find|exact|specific|details?|breakdown|"
                r"underlying|itemi[sz]ed)\b.*\b(expenses?|costs?|records?)\b|"
                r"\b(which|what)\s+(?:one|was|were|is|are)\b",
                question,
                re.IGNORECASE,
            )
        )

    @classmethod
    def _resolve_expense_history_dates(
        cls,
        arguments: ExpenseHistoryToolArguments,
        question: str,
        previous_expense_period: tuple[date, date] | None,
    ) -> tuple[date | None, date | None]:
        from_date, to_date = resolve_tool_date_range(
            arguments,
            question,
            default_period="full_history",
        )
        if (
            from_date is None
            and to_date is None
            and cls._is_expense_detail_follow_up(question)
            and previous_expense_period is not None
        ):
            return previous_expense_period
        return from_date, to_date

    @classmethod
    def _safe_contact_balances(
        cls,
        ledger: AccountLedgerResponse,
        *,
        contact_name: str | None,
    ) -> dict[str, Any]:
        if contact_name:
            matches = cls._matching_accounts(ledger, contact_name)
            if not matches:
                return {
                    "match_status": "not_found",
                    "requested_name": cls._safe_contact_name(contact_name),
                    "accounts": [],
                }
            if len(matches) > 1:
                return {
                    "match_status": "ambiguous",
                    "accounts": [
                        cls._safe_account(account) for account in matches
                    ],
                }
        else:
            matches = [
                account
                for account in ledger.accounts
                if account.contact_id is not None
            ]

        total_accounts = len(matches)
        matches = matches[:200]
        return {
            "match_status": "matched" if contact_name else "all_accounts",
            "account_count": total_accounts,
            "accounts_truncated": total_accounts > len(matches),
            "accounts": [cls._safe_account(account) for account in matches],
            "balance_sign_guide": (
                "Each balance is the current net lifetime account balance. "
                "Use balance_status to interpret who owes whom."
            ),
        }

    @staticmethod
    def _matching_accounts(
        ledger: AccountLedgerResponse,
        contact_name: str,
    ) -> list[Any]:
        normalized = contact_name.strip().casefold()
        return [
            account
            for account in ledger.accounts
            if account.contact_id is not None
            and account.contact_name.strip().casefold() == normalized
        ]

    @classmethod
    def _safe_account(cls, account: Any) -> dict[str, Any]:
        return {
            "contact_name": cls._safe_contact_name(account.contact_name),
            "roles": account.roles,
            "balance": format(account.balance, "f"),
            "balance_status": cls._balance_status(account.balance, account.roles),
            "last_activity": (
                account.last_activity.isoformat()
                if account.last_activity is not None
                else None
            ),
        }

    @staticmethod
    def _safe_contact_name(name: str) -> str:
        without_email = _CONTACT_EMAIL_PATTERN.sub("[redacted]", name)
        return _CONTACT_PHONE_PATTERN.sub("[redacted]", without_email)

    @classmethod
    def _collect_assistant_hrefs(cls, value: Any) -> set[str]:
        if isinstance(value, dict):
            hrefs: set[str] = set()
            for key, child in value.items():
                if (
                    key == "href"
                    and isinstance(child, str)
                    and child.startswith("/")
                    and not child.startswith("//")
                ):
                    hrefs.add(child)
                else:
                    hrefs.update(
                        cls._collect_assistant_hrefs(child)
                    )
            return hrefs
        if isinstance(value, list):
            return set().union(
                *(cls._collect_assistant_hrefs(item) for item in value)
            )
        return set()

    @staticmethod
    def _remove_unverified_assistant_links(
        answer: str,
        verified_hrefs: set[str],
    ) -> str:
        markdown_link = re.compile(r"\[([^\]]+)\]\((/[^)\s]*)\)")
        return markdown_link.sub(
            lambda match: (
                match.group(0)
                if match.group(2) in verified_hrefs
                else match.group(1)
            ),
            answer,
        )

    @classmethod
    def _safe_ledger_event_description(cls, event: Any) -> str:
        if event.event_type == "transaction":
            product_summary = event.description.rsplit(" · ", 1)[-1]
            return (
                f"{event.transaction_type.title()} · "
                f"{cls._safe_contact_name(product_summary)}"
            )
        if event.event_type == "payment":
            return "Payment recorded"
        if event.event_type == "settlement":
            return "Settlement recorded"
        if event.event_type == "return":
            return "Return recorded"
        if event.event_type == "refund":
            return "Refund recorded"
        if event.event_type == "replacement":
            return "Supplier replacement recorded"
        return "Account event recorded"

    @staticmethod
    def _balance_status(balance: Decimal, roles: list[str]) -> str:
        if abs(balance) < Decimal("0.005"):
            return "settled"
        is_customer = "customer" in roles
        is_supplier = "supplier" in roles
        if is_customer and is_supplier:
            return "net_receivable" if balance > 0 else "net_payable"
        if is_supplier:
            return "supplier_credit" if balance > 0 else "farm_owes_supplier"
        if is_customer:
            return "customer_owes_farm" if balance > 0 else "customer_credit"
        return "farm_is_owed" if balance > 0 else "farm_owes"

    @staticmethod
    def _safe_settlement_components(event: Any) -> dict[str, str]:
        totals = {
            "cash": Decimal("0.00"),
            "goods": Decimal("0.00"),
            "service": Decimal("0.00"),
        }
        for component in event.components:
            if component.kind in totals:
                totals[component.kind] += component.amount
        return {
            kind: format(amount, "f")
            for kind, amount in totals.items()
            if amount
        }

    @staticmethod
    def _safe_report_context(
        report: ProfitabilityReportResponse,
    ) -> dict[str, Any]:
        def money(value: Decimal | None) -> str | None:
            return format(value, "f") if value is not None else None

        return {
            "period": {
                "from": report.from_date.isoformat(),
                "to": report.to_date.isoformat(),
            },
            "accounting_basis": report.accounting_basis,
            "calculation_formula": (
                "net_revenue - cost_of_goods_sold - operating_expenses - inventory_losses"
            ),
            "report_complete": report.complete,
            "incompleteness_reason_count": len(report.incompleteness_reasons),
            "gross_sales": money(report.gross_sales),
            "sales_credits": money(report.sales_credits),
            "net_revenue": money(report.net_revenue),
            "cost_of_goods_sold": money(report.cost_of_goods_sold),
            "product_consumption_cost": money(report.product_consumption_cost),
            "egg_production_cost_allocated": money(
                report.egg_production_cost_allocated
            ),
            "operating_expenses": money(report.operating_expenses),
            "inventory_losses": money(report.inventory_losses),
            "net_profit": money(report.net_profit),
            "closing_stock_valued_cost": money(report.closing_stock_valued_cost),
            "closing_stock_unvalued_quantity": money(
                report.closing_stock_unvalued_quantity
            ),
            "untracked_chicken_quantity": money(report.untracked_chicken_quantity),
            "untracked_egg_quantity": money(report.untracked_egg_quantity),
            "unvalued_period_movement_count": report.unvalued_period_movement_count,
            "missing_inventory_record_count": report.missing_inventory_record_count,
        }
