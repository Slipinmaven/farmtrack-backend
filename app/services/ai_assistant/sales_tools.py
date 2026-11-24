from decimal import Decimal
from typing import Any

from app.core.config import settings
from app.core.exceptions import AppError
from app.services.ai_assistant.contracts import (
    PurchaseHistoryToolArguments,
    SalesHistoryToolArguments,
    SalesReportToolArguments,
    TransactionDetailsToolArguments,
)
from app.services.ai_assistant.date_ranges import (
    resolve_sales_report_period,
    resolve_tool_date_range,
)
from app.services.ai_assistant.service_context import AssistantToolHandlerBase
from app.schemas.receipt_history import ReceiptHistoryFilters
from app.schemas.sales_report import SalesReportFilters


class SalesToolHandlers(AssistantToolHandlerBase):
    async def _handle_get_pending_deliveries(
        self,
        _arguments: dict[str, Any],
    ) -> dict[str, Any]:
        del _arguments
        if self.context.service.sales_report_service is None:
            return {
                "error": "Pending delivery capability is unavailable."
            }
        deliveries = (
            await self.context.service.sales_report_service.get_pending_deliveries(
                self.context.farm_id,
                limit=101,
            )
        )
        self.context.data_scopes.append("pending_deliveries")
        return {
            "delivery_count": min(len(deliveries), 100),
            "deliveries": [
                {
                    "date": delivery.transaction_date.isoformat(),
                    "items": [
                        {
                            "product_name": self.context.service._safe_contact_name(
                                item.product_name
                            ),
                            "quantity_remaining": format(
                                item.quantity_remaining,
                                "f",
                            ),
                            "unit_name": item.unit_name,
                        }
                        for item in delivery.items
                    ],
                    "href": f"/sales/{delivery.id}",
                }
                for delivery in deliveries[:100]
            ],
            "deliveries_truncated": len(deliveries) > 100,
        }

    async def _handle_get_purchase_history(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.context.service.purchase_history_service is None:
            raise AppError(
                "AI_ASSISTANT_UNAVAILABLE",
                "Purchase history capability is not configured.",
                503,
            )
        parsed = PurchaseHistoryToolArguments.model_validate(arguments)
        from_date, to_date = resolve_tool_date_range(
            parsed,
            self.context.question,
            default_period="full_history",
        )
        report = await self.context.service.purchase_history_service.get_history(
            self.context.farm_id,
            ReceiptHistoryFilters(
                transaction_type="purchase",
                receipt_kind="transaction",
                status="all",
                from_date=from_date,
                to_date=to_date,
                search=parsed.search,
            ),
            offset=parsed.offset,
            limit=parsed.limit,
        )
        self.context.used_from_date = from_date
        self.context.used_to_date = to_date
        self.context.data_scopes.append("purchase_history")
        return {
            "period": {
                "from_date": (
                    from_date.isoformat() if from_date is not None else None
                ),
                "to_date": (
                    to_date.isoformat() if to_date is not None else None
                ),
            },
            "total_count": report.total_count,
            "completed_total": format(report.completed_total, "f"),
            "offset": report.offset,
            "limit": report.limit,
            "has_more": (
                report.offset + len(report.items) < report.total_count
            ),
            "purchases": [
                {
                    "transaction_id": str(item.id),
                    "status": getattr(item.status, "value", item.status),
                    "date": item.transaction_date.isoformat(),
                    "supplier_name": (
                        self.context.service._safe_contact_name(item.contact_name)
                        if item.contact_name
                        else None
                    ),
                    "products": [
                        self.context.service._safe_contact_name(name)
                        for name in item.product_names
                    ],
                    "line_items": [
                        {
                            "product_name": self.context.service._safe_contact_name(
                                line_item.product_name
                            ),
                            "quantity": format(line_item.quantity, "f"),
                            "unit": self.context.service._safe_contact_name(
                                line_item.unit_name
                            ),
                        }
                        for line_item in item.line_items
                    ],
                    "total": format(item.transaction_total, "f"),
                    "payments": [
                        {
                            "date": payment.payment_date.isoformat(),
                            "amount": format(payment.amount, "f"),
                            "method": getattr(
                                payment.payment_method,
                                "value",
                                payment.payment_method,
                            ),
                        }
                        for payment in item.payments
                    ],
                    "href": f"/purchases/{item.id}",
                }
                for item in report.items
            ],
        }

    async def _handle_get_sales_history(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.context.service.sales_report_service is None:
            raise AppError(
                "AI_ASSISTANT_UNAVAILABLE",
                "Sales history capability is not configured.",
                503,
            )
        parsed = SalesHistoryToolArguments.model_validate(arguments)
        report = await self.context.service.sales_report_service.get_report(
            self.context.farm_id,
            SalesReportFilters(
                from_date=parsed.from_date,
                to_date=parsed.to_date,
                status="completed",
            ),
            offset=parsed.offset,
            limit=parsed.limit,
        )
        self.context.used_from_date = parsed.from_date
        self.context.used_to_date = parsed.to_date
        self.context.data_scopes.append("sales_history")
        return {
            "period": {
                "from_date": (
                    parsed.from_date.isoformat()
                    if parsed.from_date is not None
                    else None
                ),
                "to_date": (
                    parsed.to_date.isoformat()
                    if parsed.to_date is not None
                    else None
                ),
            },
            "total_count": report.total_count,
            "offset": report.offset,
            "limit": report.limit,
            "has_more": (
                report.offset + len(report.items) < report.total_count
            ),
            "sales": [
                {
                    "transaction_id": str(item.id),
                    "date": item.transaction_date.isoformat(),
                    "time": (
                        item.transaction_time.isoformat()
                        if item.transaction_time is not None
                        else None
                    ),
                    "customer_name": (
                        self.context.service._safe_contact_name(item.customer_name)
                        if item.customer_name is not None
                        else None
                    ),
                    "products": [
                        {
                            "name": self.context.service._safe_contact_name(product.name),
                            "quantity": format(product.quantity, "f"),
                            "unit_name": product.unit_name,
                        }
                        for product in item.products_sold
                    ],
                    "total": format(item.transaction_total, "f"),
                    "amount_paid": format(item.amount_paid, "f"),
                    "balance_due": format(item.balance_due, "f"),
                    "href": f"/sales/{item.id}",
                }
                for item in report.items
            ],
        }

    async def _handle_get_sales_report(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.context.service.sales_report_service is None:
            return {"error": "Sales report capability is unavailable."}
        parsed = SalesReportToolArguments.model_validate(arguments)
        (
            from_date,
            to_date,
            from_time,
            to_time,
        ) = resolve_sales_report_period(
            parsed,
            self.context.question,
        )
        report = await self.context.service.sales_report_service.get_report(
            self.context.farm_id,
            SalesReportFilters(
                from_date=from_date,
                to_date=to_date,
                from_time=from_time,
                to_time=to_time,
                status="completed",
            ),
            offset=0,
            limit=100,
        )
        self.context.used_from_date = from_date
        self.context.used_to_date = to_date
        product_totals: dict[tuple[str, str | None], Decimal] = {}
        for transaction in report.items:
            for item in transaction.products_sold:
                key = (item.name, item.unit_name)
                product_totals[key] = (
                    product_totals.get(key, Decimal("0"))
                    + item.quantity
                )
        ranked_products = sorted(
            product_totals.items(),
            key=lambda entry: (entry[1], entry[0][0].casefold()),
        )
        rankings_complete = report.total_count <= len(report.items)
        self.context.data_scopes.append("sales_report")
        transactions = [
            {
                "date": item.transaction_date.isoformat(),
                "time": (
                    item.transaction_time.isoformat()
                    if item.transaction_time is not None
                    else None
                ),
                "customer_name": (
                    self.context.service._safe_contact_name(item.customer_name)
                    if item.customer_name is not None
                    else None
                ),
                "products": [
                    {
                        "name": self.context.service._safe_contact_name(product.name),
                        "quantity": format(product.quantity, "f"),
                        "unit_name": product.unit_name,
                    }
                    for product in item.products_sold
                ],
                "total": format(item.transaction_total, "f"),
                "amount_paid": format(item.amount_paid, "f"),
                "balance_due": format(item.balance_due, "f"),
                "href": f"/sales/{item.id}",
            }
            for item in report.items
        ]
        return {
            "period": {
                "from_date": from_date.isoformat(),
                "to_date": to_date.isoformat(),
                "from_time": (
                    from_time.isoformat() if from_time is not None else None
                ),
                "to_time_exclusive": (
                    to_time.isoformat() if to_time is not None else None
                ),
                "timezone": settings.timezone,
                "records_without_times_excluded": (
                    from_time is not None
                ),
            },
            "transaction_count": report.summary.transaction_count,
            "transactions_truncated": (
                report.total_count > len(report.items)
            ),
            "sales_total": format(report.summary.sales_total, "f"),
            "amount_received": format(
                report.summary.amount_received,
                "f",
            ),
            "balance_due": format(report.summary.balance_due, "f"),
            "transactions": transactions,
            "product_ranking_complete": rankings_complete,
            "product_ranking": [
                {
                    "product_name": self.context.service._safe_contact_name(name),
                    "unit_name": unit_name,
                    "quantity_sold": format(quantity, "f"),
                }
                for (name, unit_name), quantity in (
                    ranked_products[:100]
                    if rankings_complete
                    else []
                )
            ],
            "least_sold_products": [
                {
                    "product_name": self.context.service._safe_contact_name(name),
                    "unit_name": unit_name,
                    "quantity_sold": format(quantity, "f"),
                }
                for (name, unit_name), quantity in (
                    ranked_products[:5]
                    if rankings_complete
                    else []
                )
            ],
            "top_sold_products": [
                {
                    "product_name": self.context.service._safe_contact_name(name),
                    "unit_name": unit_name,
                    "quantity_sold": format(quantity, "f"),
                }
                for (name, unit_name), quantity in (
                    list(reversed(ranked_products[-5:]))
                    if rankings_complete
                    else []
                )
            ],
        }

    async def _handle_get_transaction_details(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if (
            self.context.farm is None
            or self.context.service.transaction_repository is None
        ):
            raise AppError(
                "AI_ASSISTANT_UNAVAILABLE",
                "Transaction history capability is not configured.",
                503,
            )
        parsed = TransactionDetailsToolArguments.model_validate(arguments)
        details = await self.context.service._read_transaction_details(
            farm=self.context.farm,
            transaction_id=parsed.transaction_id,
            transaction_type=parsed.transaction_type,
        )
        if details is None:
            return {
                "match_status": "not_found",
                "transaction_type": parsed.transaction_type,
            }
        self.context.data_scopes.append("transaction_details")
        return details
