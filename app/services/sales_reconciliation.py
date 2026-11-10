from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Iterable

from app.schemas.enums import TransactionStatus

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class SalesReconciliationRecord:
    transaction_date: date
    status: TransactionStatus
    transaction_total: Decimal
    payments: Decimal
    refunds: Decimal
    return_credits: Decimal
    settlements: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class SalesReconciliationSummary:
    transaction_count: int
    sales_total: Decimal
    amount_received: Decimal
    balance_due: Decimal
    return_credits: Decimal
    goods_settlements: Decimal
    service_settlements: Decimal
    customer_credit: Decimal
    unallocated_amount: Decimal


def summarize_sales(
    records: Iterable[SalesReconciliationRecord],
    *,
    from_date: date | None,
    to_date: date | None,
) -> SalesReconciliationSummary:
    transaction_count = 0
    sales_total = ZERO
    amount_received = ZERO
    balance_due = ZERO
    return_credits = ZERO
    goods_settlements = ZERO
    service_settlements = ZERO
    customer_credit = ZERO

    for record in records:
        if record.status != TransactionStatus.COMPLETED:
            continue
        if from_date is not None and record.transaction_date < from_date:
            continue
        if to_date is not None and record.transaction_date > to_date:
            continue

        settlement_applied = ZERO
        cash_settlements = ZERO
        goods_settlement_value = ZERO
        service_settlement_value = ZERO
        for settlement in record.settlements:
            toward_farm = settlement["direction"] == "contact_to_farm"
            sign = Decimal("1.00") if toward_farm else Decimal("-1.00")
            settlement_applied += Decimal(settlement["total_value"]) * sign
            for line in settlement["lines"]:
                if line["kind"] == "cash":
                    cash_settlements += Decimal(line["amount"]) * sign
                elif line["kind"] == "goods":
                    goods_settlement_value += Decimal(line["value"]) * sign
                elif line["kind"] == "service":
                    service_settlement_value += Decimal(line["value"]) * sign

        net_payments = record.payments - record.refunds
        received = net_payments + cash_settlements
        adjusted_total = max(
            record.transaction_total - record.return_credits,
            ZERO,
        )
        applied_return_credit = record.transaction_total - adjusted_total
        amount_applied = net_payments + settlement_applied
        owed = max(
            adjusted_total - amount_applied,
            ZERO,
        )
        credit = max(amount_applied - adjusted_total, ZERO)
        transaction_count += 1
        sales_total += record.transaction_total
        amount_received += received
        balance_due += owed
        return_credits += applied_return_credit
        goods_settlements += goods_settlement_value
        service_settlements += service_settlement_value
        customer_credit += credit

    return SalesReconciliationSummary(
        transaction_count=transaction_count,
        sales_total=sales_total,
        amount_received=amount_received,
        balance_due=balance_due,
        return_credits=return_credits,
        goods_settlements=goods_settlements,
        service_settlements=service_settlements,
        customer_credit=customer_credit,
        unallocated_amount=sales_total - amount_received - balance_due,
    )
