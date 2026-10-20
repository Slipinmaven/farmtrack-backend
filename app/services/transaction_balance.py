from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.schemas.enums import TransactionType

@dataclass(frozen=True)
class TransactionBalance:
    adjusted_transaction_total: Decimal
    amount_paid: Decimal
    balance_due: Decimal
    credit_balance: Decimal


def get_settlement_adjustment(transaction: Any) -> Decimal:
    adjustment = Decimal("0.00")
    transaction_type = transaction.transaction_type
    for settlement in getattr(transaction, "settlements", ()):
        toward_farm = settlement.direction == "contact_to_farm"
        sign = (
            1
            if (transaction_type == TransactionType.SALE and toward_farm)
            or (transaction_type == TransactionType.PURCHASE and not toward_farm)
            else -1
        )
        adjustment += Decimal(settlement.total_value) * sign
    return adjustment


def calculate_transaction_balance(
    transaction_total: Decimal,
    amount_received: Decimal,
    amount_refunded: Decimal,
    credit_notes: Decimal,
    *,
    settlement_adjustment: Decimal = Decimal("0.00"),
) -> TransactionBalance:
    adjusted_total = max(transaction_total - credit_notes, Decimal("0.00"))
    amount_paid = amount_received - amount_refunded + settlement_adjustment
    return TransactionBalance(
        adjusted_transaction_total=adjusted_total,
        amount_paid=amount_paid,
        balance_due=max(adjusted_total - amount_paid, Decimal("0.00")),
        credit_balance=max(amount_paid - adjusted_total, Decimal("0.00")),
    )