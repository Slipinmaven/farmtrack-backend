from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from app.core.exceptions import AppError
from app.models.farm import Farm
from app.services.ai_assistant.service_context import AssistantServiceContext


class FarmAssistantTransactionMixin(AssistantServiceContext):
    async def _read_transaction_details(
        self,
        *,
        farm: Farm,
        transaction_id: UUID,
        transaction_type: Literal["sale", "purchase"],
    ) -> dict[str, Any] | None:
        repository = self.transaction_repository
        if repository is None:
            raise AppError(
                "AI_ASSISTANT_UNAVAILABLE",
                "Transaction history capability is not configured.",
                503,
            )
        def enum_value(value: Any) -> Any:
            return value.value if hasattr(value, "value") else value

        transaction = (
            await repository.get_sale_detail_by_id(farm.id, transaction_id)
            if transaction_type == "sale"
            else await repository.get_purchase_detail_by_id(farm.id, transaction_id)
        )
        if (
            transaction is None
            or enum_value(transaction.transaction_type) != transaction_type
        ):
            return None

        def iso_value(value: Any) -> str | None:
            return value.isoformat() if value is not None else None

        items = list(transaction.items)
        item_names = {
            item.id: self._safe_contact_name(item.product.name)
            for item in items
        }
        lines = [
            {
                "product_name": item_names[item.id],
                "product_type": enum_value(item.product.product_type),
                "quantity": format(item.quantity, "f"),
                "unit_name": item.unit.name,
                "unit_abbreviation": item.unit.abbreviation,
                "base_unit_quantity": format(
                    item.quantity * item.conversion_factor,
                    "f",
                ),
                "unit_price": format(item.unit_price, "f"),
                "line_total": format(item.total_amount, "f"),
            }
            for item in items
        ]
        line_items_total = sum(
            (item.total_amount for item in items),
            Decimal("0"),
        )
        payments = [
            {
                "date": iso_value(payment.payment_date),
                "time": iso_value(payment.payment_time),
                "amount": format(payment.amount, "f"),
                "method": enum_value(payment.payment_method),
            }
            for payment in transaction.payments
        ]
        settlements = []
        for settlement in transaction.settlements:
            safe_lines = []
            for line in settlement.lines:
                kind = line.get("kind")
                safe_line: dict[str, Any] = {"kind": kind}
                if kind == "cash":
                    safe_line.update(
                        {
                            "amount": line.get("amount"),
                            "payment_method": line.get("payment_method"),
                        }
                    )
                elif kind == "goods":
                    safe_line.update(
                        {
                            "quantity": line.get("quantity"),
                            "agreed_unit_value": line.get("agreed_unit_value"),
                        }
                    )
                elif kind == "service":
                    safe_line["value"] = line.get("value")
                safe_lines.append(safe_line)
            settlements.append(
                {
                    "date": iso_value(settlement.settlement_date),
                    "direction": enum_value(settlement.direction),
                    "total": format(settlement.total_value, "f"),
                    "components": safe_lines,
                }
            )

        activity: dict[str, Any] = {
            "payments": payments[:100],
            "settlements": settlements[:100],
        }
        truncated: dict[str, bool] = {
            "payments": len(payments) > 100,
            "settlements": len(settlements) > 100,
        }

        if transaction_type == "sale":
            if (
                self.transaction_refund_service is None
                or self.sale_return_service is None
                or self.sale_delivery_service is None
            ):
                raise AppError(
                    "AI_ASSISTANT_UNAVAILABLE",
                    "Sale refund, return, or delivery history is not configured.",
                    503,
                )
            refunds = await self.transaction_refund_service.list_refunds(
                farm.id,
                transaction_id,
            )
            returns = await self.sale_return_service.list_returns(
                farm.id,
                transaction_id,
            )
            deliveries = await self.sale_delivery_service.list_deliveries(
                farm.id,
                transaction_id,
            )
            activity["refunds"] = [
                {
                    "date": iso_value(refund.refund_date),
                    "time": iso_value(refund.refund_time),
                    "amount": format(refund.amount, "f"),
                    "method": enum_value(refund.payment_method),
                }
                for refund in refunds[:100]
            ]
            truncated["refunds"] = len(refunds) > 100
            activity["returns"] = [
                {
                    "date": iso_value(item.return_date),
                    "time": iso_value(item.return_time),
                    "type": enum_value(item.return_type),
                    "credit_total": format(item.credit_total, "f"),
                    "items": [
                        {
                            "product_name": self._safe_contact_name(
                                returned.product_name
                            ),
                            "quantity": format(returned.quantity, "f"),
                            "credit_amount": format(returned.credit_amount, "f"),
                        }
                        for returned in item.items
                    ],
                }
                for item in returns[:100]
            ]
            activity["deliveries"] = [
                {
                    "date": iso_value(delivery.delivered_date),
                    "time": iso_value(delivery.delivered_time),
                    "items": [
                        {
                            "product_name": item_names.get(
                                delivered.transaction_item_id
                            ),
                            "quantity_delivered": format(
                                delivered.quantity_delivered,
                                "f",
                            ),
                            "quantity_remaining": format(
                                delivered.remaining_quantity,
                                "f",
                            ),
                        }
                        for delivered in delivery.items
                    ],
                }
                for delivery in deliveries[:100]
            ]
            truncated["returns"] = len(returns) > 100
            truncated["deliveries"] = len(deliveries) > 100
        else:
            if (
                self.purchase_return_service is None
                or self.purchase_replacement_service is None
                or self.purchase_supplier_refund_service is None
            ):
                raise AppError(
                    "AI_ASSISTANT_UNAVAILABLE",
                    "Purchase return history is not configured.",
                    503,
                )
            returns = await self.purchase_return_service.list_returns(
                farm.id,
                transaction_id,
            )
            replacements = await self.purchase_replacement_service.list_replacements(
                farm.id,
                transaction_id,
            )
            supplier_refunds = (
                await self.purchase_supplier_refund_service.list_refunds(
                    farm.id,
                    transaction_id,
                )
            )
            return_item_names = {
                returned_item.id: self._safe_contact_name(
                    returned_item.product_name
                )
                for purchase_return in returns
                for returned_item in purchase_return.items
            }
            activity["returns"] = [
                {
                    "date": iso_value(item.return_date),
                    "time": iso_value(item.return_time),
                    "credit_total": format(item.credit_total, "f"),
                    "items": [
                        {
                            "product_name": self._safe_contact_name(
                                returned.product_name
                            ),
                            "quantity_returned": format(
                                returned.quantity_returned,
                                "f",
                            ),
                            "credit_amount": format(returned.credit_amount, "f"),
                        }
                        for returned in item.items
                    ],
                }
                for item in returns[:100]
            ]
            activity["replacements"] = [
                {
                    "date": iso_value(item.replacement_date),
                    "time": iso_value(item.replacement_time),
                    "credit_applied_total": format(
                        item.credit_applied_total,
                        "f",
                    ),
                    "items": [
                        {
                            "product_name": return_item_names.get(
                                replacement.purchase_return_item_id
                            ),
                            "quantity_received": format(
                                replacement.quantity_received,
                                "f",
                            ),
                            "replacement_quantity": format(
                                replacement.replacement_quantity,
                                "f",
                            ),
                            "bonus_quantity": format(
                                replacement.bonus_quantity,
                                "f",
                            ),
                            "credit_applied_amount": format(
                                replacement.credit_applied_amount,
                                "f",
                            ),
                        }
                        for replacement in item.items
                    ],
                }
                for item in replacements[:100]
            ]
            activity["supplier_refunds"] = [
                {
                    "date": iso_value(refund.refund_date),
                    "time": iso_value(refund.refund_time),
                    "product_name": return_item_names.get(
                        refund.purchase_return_item_id
                    ),
                    "amount": format(refund.amount, "f"),
                    "method": enum_value(refund.payment_method),
                }
                for refund in supplier_refunds[:100]
            ]
            truncated["returns"] = len(returns) > 100
            truncated["replacements"] = len(replacements) > 100
            truncated["supplier_refunds"] = len(supplier_refunds) > 100

            product_types = {
                str(enum_value(item.product.product_type)).casefold()
                for item in items
            }
            if "chickens" in product_types:
                if self.chicken_purchase_details_service is None:
                    raise AppError(
                        "AI_ASSISTANT_UNAVAILABLE",
                        "Chicken purchase receipt history is not configured.",
                        503,
                    )
                purchase_details = (
                    await self.chicken_purchase_details_service.get_details(
                        farm.id,
                        transaction_id,
                    )
                )
                receipts = purchase_details.receipts
                activity["receipts"] = [
                    {
                        "date": iso_value(receipt.received_date),
                        "time": iso_value(receipt.received_time),
                        "items": [
                            {
                                "product_name": item_names.get(
                                    received.transaction_item_id
                                ),
                                "quantity_received": format(
                                    received.quantity_received,
                                    "f",
                                ),
                                "quantity_remaining": format(
                                    received.remaining_quantity,
                                    "f",
                                ),
                                "batch_name": self._safe_contact_name(
                                    received.batch_name
                                )
                                if received.batch_name
                                else None,
                                "block_allocations": [
                                    {
                                        "block_name": self._safe_contact_name(
                                            allocation.block_name
                                        ),
                                        "quantity": format(
                                            allocation.quantity,
                                            "f",
                                        ),
                                    }
                                    for allocation in received.block_allocations
                                ],
                            }
                            for received in receipt.items
                        ],
                    }
                    for receipt in receipts[:100]
                ]
                truncated["receipts"] = len(receipts) > 100

        return {
            "transaction": {
                "transaction_id": str(transaction.id),
                "transaction_type": transaction_type,
                "status": enum_value(transaction.status),
                "date": iso_value(transaction.transaction_date),
                "time": iso_value(transaction.transaction_time),
                "line_items_total": format(line_items_total, "f"),
                "transaction_discount_amount": (
                    format(transaction.discount_amount, "f")
                    if transaction.discount_amount is not None
                    else None
                ),
                "items": lines,
            },
            "activity": activity,
            "activity_truncated": truncated,
            "href": (
                f"/sales/{transaction.id}"
                if transaction_type == "sale"
                else f"/purchases/{transaction.id}"
            ),
        }
