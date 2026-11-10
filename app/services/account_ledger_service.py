from datetime import date, time
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.core.unit_of_work import UnitOfWork
from app.repositories.transaction_repository import TransactionRepository
from app.schemas.account_ledger import (
    AccountLedgerAccount,
    AccountLedgerComponent,
    AccountLedgerEvent,
    AccountLedgerResponse,
)
from app.schemas.enums import TransactionStatus, TransactionType


class AccountLedgerService:
    def __init__(
        self,
        transaction_repository: TransactionRepository,
        unit_of_work: UnitOfWork,
    ) -> None:
        self.transaction_repository = transaction_repository
        self.unit_of_work = unit_of_work

    async def get_ledger(
        self,
        farm_id: UUID,
        *,
        contact_id: UUID | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> AccountLedgerResponse:
        async with self.unit_of_work:
            transactions = await self.transaction_repository.list_for_account_ledger(
                farm_id
            )
            raw_events: list[dict[str, object]] = []
            for transaction in transactions:
                transaction_type = transaction.transaction_type.value
                transaction_total = sum(
                    (item.total_amount for item in transaction.items),
                    Decimal("0.00"),
                )
                contact = transaction.contact
                common = {
                    "transaction_id": transaction.id,
                    "transaction_type": transaction_type,
                    "contact_id": transaction.contact_id,
                    "contact_name": contact.name if contact else None,
                    "contact_roles": (
                        [
                            role.role.value
                            for role in getattr(contact, "contact_roles", [])
                        ]
                        if contact
                        else []
                    ),
                    "reference_number": transaction.reference_number,
                }
                product_summary = self._product_summary(transaction.items)
                transaction_amount = (
                    Decimal("0.00")
                    if transaction.status == TransactionStatus.CANCELLED
                    else transaction_total
                    if transaction.transaction_type == TransactionType.SALE
                    else -transaction_total
                )
                transaction_description = (
                    f"{transaction_type.title()} · {product_summary}"
                    if product_summary
                    else f"{transaction_type.title()} recorded"
                )
                if transaction.status == TransactionStatus.CANCELLED:
                    transaction_description = f"Cancelled · {transaction_description}"
                self._append_event(
                    raw_events,
                    common,
                    event_id=f"transaction:{transaction.id}",
                    event_type="transaction",
                    event_date=transaction.transaction_date,
                    event_time=transaction.transaction_time,
                    description=transaction_description,
                    amount=transaction_amount,
                    priority=0,
                )
                for payment in transaction.payments:
                    amount = payment.amount
                    signed_amount = (
                        -amount
                        if transaction.transaction_type == TransactionType.SALE
                        else amount
                    )
                    self._append_event(
                        raw_events,
                        common,
                        event_id=f"payment:{payment.id}",
                        event_type="payment",
                        event_date=payment.payment_date,
                        event_time=payment.payment_time,
                        description=f"Payment · {payment.payment_method.value}",
                        amount=signed_amount,
                        payment_method=payment.payment_method.value,
                        payment_reference=payment.reference_number,
                        priority=1,
                    )
                for settlement in transaction.settlements:
                    signed_amount = settlement.total_value
                    if (
                        transaction.transaction_type == TransactionType.SALE
                        and settlement.direction == "contact_to_farm"
                    ) or (
                        transaction.transaction_type == TransactionType.PURCHASE
                        and settlement.direction == "contact_to_farm"
                    ):
                        signed_amount = -signed_amount
                    self._append_event(
                        raw_events,
                        common,
                        event_id=f"settlement:{settlement.id}",
                        event_type="settlement",
                        event_date=settlement.settlement_date,
                        event_time=None,
                        description=self._settlement_description(settlement),
                        amount=signed_amount,
                        cash_amount=self._settlement_cash_amount(settlement),
                        components=self._settlement_components(settlement),
                        sort_time=settlement.created_at.time(),
                        priority=2,
                    )
                if transaction.transaction_type == TransactionType.SALE:
                    for sale_return in transaction.sale_returns:
                        amount = sum(
                            (item.credit_amount for item in sale_return.items),
                            Decimal("0.00"),
                        )
                        self._append_event(
                            raw_events,
                            common,
                            event_id=f"return:{sale_return.id}",
                            event_type="return",
                            event_date=sale_return.return_date,
                            event_time=sale_return.return_time,
                            description=f"Sale return · {sale_return.reason}",
                            amount=-amount,
                            priority=3,
                        )
                    for refund in transaction.refunds:
                        self._append_event(
                            raw_events,
                            common,
                            event_id=f"refund:{refund.id}",
                            event_type="refund",
                            event_date=refund.refund_date,
                            event_time=refund.refund_time,
                            description=f"Refund · {refund.payment_method.value} · {refund.reason}",
                            amount=refund.amount,
                            payment_method=refund.payment_method.value,
                            payment_reference=refund.reference_number,
                            priority=4,
                        )
                else:
                    for purchase_return in transaction.purchase_returns:
                        amount = sum(
                            (item.credit_amount for item in purchase_return.items),
                            Decimal("0.00"),
                        )
                        self._append_event(
                            raw_events,
                            common,
                            event_id=f"return:{purchase_return.id}",
                            event_type="return",
                            event_date=purchase_return.return_date,
                            event_time=purchase_return.return_time,
                            description=f"Purchase return · {purchase_return.reason}",
                            amount=amount,
                            priority=3,
                        )
                    for refund in transaction.purchase_supplier_refunds:
                        self._append_event(
                            raw_events,
                            common,
                            event_id=f"refund:{refund.id}",
                            event_type="refund",
                            event_date=refund.refund_date,
                            event_time=refund.refund_time,
                            description=f"Supplier refund · {refund.payment_method.value} · {refund.reason}",
                            amount=-refund.amount,
                            payment_method=refund.payment_method.value,
                            payment_reference=refund.reference_number,
                            priority=4,
                        )
                    for replacement in transaction.purchase_replacements:
                        amount = sum(
                            (item.credit_applied_amount for item in replacement.items),
                            Decimal("0.00"),
                        )
                        self._append_event(
                            raw_events,
                            common,
                            event_id=f"replacement:{replacement.id}",
                            event_type="replacement",
                            event_date=replacement.replacement_date,
                            event_time=replacement.replacement_time,
                            description="Supplier replacement",
                            amount=-amount,
                            priority=5,
                        )

            raw_events.sort(key=lambda event: event["sort_key"])
            account_balances: dict[UUID | None, Decimal] = {}
            last_activity: dict[UUID | None, date] = {}
            for event in raw_events:
                event_contact_id = event["contact_id"]
                amount = event["amount"]
                event_date = event["event_date"]
                if isinstance(amount, Decimal) and isinstance(event_date, date):
                    account_balances[event_contact_id] = (
                        account_balances.get(event_contact_id, Decimal("0.00"))
                        + amount
                    )
                    last_activity[event_contact_id] = max(
                        last_activity.get(event_contact_id, event_date),
                        event_date,
                    )

            running_balances: dict[UUID | None, Decimal] = {}
            events: list[AccountLedgerEvent] = []
            opening_balance = Decimal("0.00")
            period_delta = Decimal("0.00")

            for event in raw_events:
                event_contact_id = event["contact_id"]
                balance = running_balances.get(event_contact_id, Decimal("0.00"))
                event_date = event["event_date"]
                amount = event["amount"]
                if not isinstance(event_date, date) or not isinstance(amount, Decimal):
                    continue
                if from_date is not None and event_date < from_date:
                    running_balances[event_contact_id] = balance + amount
                    if event_contact_id == contact_id:
                        opening_balance += amount
                    continue
                if to_date is not None and event_date > to_date:
                    continue
                if contact_id is not None and event_contact_id != contact_id:
                    running_balances[event_contact_id] = balance + amount
                    continue

                balance = running_balances.get(event_contact_id, Decimal("0.00")) + amount
                running_balances[event_contact_id] = balance
                period_delta += amount
                event["running_balance"] = balance
                events.append(
                    AccountLedgerEvent(
                        id=str(event["id"]),
                        transaction_id=event["transaction_id"],
                        transaction_type=event["transaction_type"],
                        contact_id=event_contact_id,
                        contact_name=event["contact_name"],
                        event_type=event["event_type"],
                        event_date=event_date,
                        event_time=event["event_time"],
                        reference_number=event["reference_number"],
                        description=event["description"],
                        amount=amount,
                        running_balance=balance,
                        payment_method=event.get("payment_method"),
                        payment_reference=event.get("payment_reference"),
                        cash_amount=event.get("cash_amount"),
                        components=event.get("components", []),
                    )
                )

            accounts = [
                AccountLedgerAccount(
                    contact_id=account_id,
                    contact_name=(
                        next(
                            (
                                str(event["contact_name"])
                                for event in raw_events
                                if event["contact_id"] == account_id
                                and event["contact_name"]
                            ),
                            "No contact assigned",
                        )
                    ),
                    roles=next(
                        (
                            event["contact_roles"]
                            for event in raw_events
                            if event["contact_id"] == account_id
                        ),
                        [],
                    ),
                    balance=balance,
                    last_activity=last_activity.get(account_id),
                )
                for account_id, balance in account_balances.items()
            ]
            accounts.sort(key=lambda account: (-abs(account.balance), account.contact_name.casefold()))
            return AccountLedgerResponse(
                events=events,
                accounts=accounts,
                opening_balance=opening_balance if contact_id is not None else None,
                closing_balance=(
                    opening_balance + period_delta
                    if contact_id is not None
                    else None
                ),
            )

    @staticmethod
    def _append_event(
        events: list[dict[str, object]],
        common: dict[str, object],
        *,
        event_id: str,
        event_type: str,
        event_date: date,
        event_time: time | None,
        description: str,
        amount: Decimal,
        priority: int,
        sort_time: time | None = None,
        cash_amount: Decimal | None = None,
        payment_method: str | None = None,
        payment_reference: str | None = None,
        components: list[AccountLedgerComponent] | None = None,
    ) -> None:
        events.append(
            {
                **common,
                "id": event_id,
                "event_type": event_type,
                "event_date": event_date,
                "event_time": event_time,
                "description": description,
                "amount": amount,
                "sort_key": (
                    event_date,
                    sort_time or event_time or time.min,
                    priority,
                    event_id,
                ),
                "cash_amount": cash_amount,
                "payment_method": payment_method,
                "payment_reference": payment_reference,
                "components": components or [],
            }
        )

    @staticmethod
    def _settlement_description(settlement: Any) -> str:
        details: list[str] = []
        for line in getattr(settlement, "lines", []):
            kind = line.get("kind")
            if kind == "cash":
                detail = f"Cash via {line.get('payment_method', 'payment method')}"
                reference = line.get("reference_number")
                if reference:
                    detail += f" · {reference}"
                details.append(detail)
            elif kind == "service":
                details.append(f"Service: {line.get('description', 'recorded')}")
            elif kind == "goods":
                name = line.get("product_name", "Goods")
                quantity = line.get("quantity")
                unit = line.get("unit_name")
                if quantity is not None:
                    name += f" × {quantity}"
                if unit:
                    name += f" {unit}"
                details.append(name)

        description = "Settlement"
        if details:
            description += f" · {'; '.join(details)}"
        return description

    @staticmethod
    def _settlement_cash_amount(settlement: Any) -> Decimal | None:
        cash_lines = [
            line
            for line in getattr(settlement, "lines", [])
            if line.get("kind") == "cash"
        ]
        if not cash_lines:
            return None
        return sum(
            (
                Decimal(str(line.get("value", line.get("amount", "0"))))
                for line in cash_lines
            ),
            Decimal("0.00"),
        )

    @staticmethod
    def _settlement_components(settlement: Any) -> list[AccountLedgerComponent]:
        components: list[AccountLedgerComponent] = []
        for line in getattr(settlement, "lines", []):
            kind = line.get("kind")
            value = line.get("value", line.get("amount"))
            if kind not in {"cash", "goods", "service"} or value is None:
                continue
            amount = Decimal(str(value))
            if amount <= 0:
                continue
            if kind == "cash":
                payment_method = str(line.get("payment_method", "Payment"))
                label = payment_method.replace("_", " ").title()
                if payment_method.casefold() == "mpesa":
                    label = "M-Pesa"
                components.append(
                    AccountLedgerComponent(
                        kind="cash",
                        label=label,
                        amount=amount,
                        payment_method=payment_method,
                        reference_number=line.get("reference_number"),
                    )
                )
            elif kind == "service":
                components.append(
                    AccountLedgerComponent(
                        kind="service",
                        label=str(line.get("description", "Service")),
                        amount=amount,
                    )
                )
            else:
                product_name = str(line.get("product_name", "Goods"))
                quantity = line.get("quantity")
                unit_name = line.get("unit_name")
                quantity_label = ""
                if quantity is not None:
                    readable_quantity = format(
                        Decimal(str(quantity)).normalize(),
                        "f",
                    )
                    quantity_decimal = Decimal(str(quantity))
                    quantity_label = f" · {readable_quantity}"
                    if unit_name:
                        quantity_label += (
                            f" {AccountLedgerService._pluralize_unit(unit_name, quantity_decimal)}"
                        )
                components.append(
                    AccountLedgerComponent(
                        kind="goods",
                        label=f"{product_name}{quantity_label}",
                        amount=amount,
                    )
                )
        return components

    @staticmethod
    def _product_summary(items: list[Any]) -> str:
        quantities: dict[tuple[str, str], Decimal] = {}
        for item in items:
            product_name = item.product.name
            unit_name = getattr(getattr(item, "unit", None), "name", "")
            key = (product_name, unit_name)
            quantities[key] = quantities.get(key, Decimal("0")) + Decimal(
                str(item.quantity)
            )

        parts = []
        for (product_name, unit_name), quantity in sorted(
            quantities.items(),
            key=lambda item: item[0][0].casefold(),
        ):
            readable_quantity = format(quantity.normalize(), "f")
            unit = AccountLedgerService._pluralize_unit(unit_name, quantity)
            parts.append(
                f"{product_name}: {readable_quantity} {unit}".strip()
                if unit
                else f"{product_name}: {readable_quantity}"
            )
        return ", ".join(parts)

    @staticmethod
    def _pluralize_unit(unit: str, quantity: Decimal) -> str:
        if not unit:
            return ""
        if quantity == Decimal("1") or unit.casefold() in {
            "kg",
            "g",
            "l",
            "ml",
        }:
            return unit.lower()
        if unit.casefold().endswith("s"):
            return unit.lower()
        if unit.casefold().endswith("y"):
            return f"{unit[:-1].lower()}ies"
        return f"{unit.lower()}s"
