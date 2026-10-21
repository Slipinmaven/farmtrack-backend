from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Mapping

CENT = Decimal("0.01")


def calculate_discount_allocation(
    line_subtotals: list[Decimal],
    discount_type: str | None,
    discount_value: Decimal,
) -> tuple[Decimal, list[Decimal]]:
    normalized_subtotals = [
        amount.quantize(CENT, rounding=ROUND_HALF_UP) for amount in line_subtotals
    ]
    line_discounts = [Decimal("0.00") for _ in normalized_subtotals]
    subtotal = sum(normalized_subtotals, Decimal("0.00"))
    if discount_type is None:
        if discount_value != 0:
            raise ValueError("Choose a discount type for the discount amount.")
        return Decimal("0.00"), line_discounts
    if discount_type not in {"fixed", "percentage"}:
        raise ValueError("Choose a valid discount type.")
    if discount_value == 0:
        return Decimal("0.00"), line_discounts
    if discount_value < 0:
        raise ValueError("A discount cannot be negative.")

    if discount_type == "percentage":
        if discount_value > Decimal("100"):
            raise ValueError("A percentage discount cannot exceed 100%.")
        discount_amount = (subtotal * discount_value / Decimal("100")).quantize(
            CENT, rounding=ROUND_HALF_UP
        )
    elif discount_type == "fixed":
        discount_amount = discount_value.quantize(CENT, rounding=ROUND_HALF_UP)
    else:
        raise ValueError("Choose a valid discount type.")

    if discount_amount > subtotal:
        raise ValueError("The discount cannot exceed the purchase subtotal.")
    if subtotal == 0:
        return Decimal("0.00"), line_discounts

    subtotal_cents = int(subtotal * 100)
    discount_cents = int(discount_amount * 100)
    allocations: list[int] = []
    remainders: list[tuple[int, int]] = []
    for index, line_subtotal in enumerate(normalized_subtotals):
        numerator = int(line_subtotal * 100) * discount_cents
        allocated, remainder = divmod(numerator, subtotal_cents)
        allocations.append(allocated)
        remainders.append((remainder, index))

    remaining_cents = discount_cents - sum(allocations)
    for _, index in sorted(remainders, reverse=True):
        if remaining_cents == 0:
            break
        if allocations[index] < int(normalized_subtotals[index] * 100):
            allocations[index] += 1
            remaining_cents -= 1

    if remaining_cents:
        raise ValueError("The discount could not be allocated to the purchase items.")

    line_discounts = [
        Decimal(amount).scaleb(-2).quantize(CENT) for amount in allocations
    ]
    return discount_amount, line_discounts


def calculate_prorated_return_credit(
    total_amount: Decimal,
    returned_quantity: Decimal,
    ordered_quantity: Decimal,
) -> Decimal:
    if ordered_quantity <= 0 or returned_quantity <= 0:
        return Decimal("0.00")
    return (total_amount * returned_quantity / ordered_quantity).quantize(
        CENT,
        rounding=ROUND_HALF_UP,
    )


def calculate_sale_return_credit_total(
    transaction_items: Iterable[object],
    returned_quantities: Mapping[object, Decimal],
) -> Decimal:
    total = Decimal("0.00")
    for item in transaction_items:
        returned_quantity = returned_quantities.get(
            getattr(item, "id", None),
            Decimal("0"),
        )
        if returned_quantity <= 0:
            continue
        ordered_quantity = (
            Decimal(str(item.quantity)) * Decimal(str(item.conversion_factor))
        )
        total += calculate_prorated_return_credit(
            Decimal(str(item.total_amount)),
            returned_quantity,
            ordered_quantity,
        )
    return total


def validate_payment_confirmation(
    final_total: Decimal,
    payment_amounts: list[Decimal],
    confirmed: bool,
) -> None:
    paid_total = sum(payment_amounts, Decimal("0.00")).quantize(
        CENT, rounding=ROUND_HALF_UP
    )
    if paid_total > final_total and not confirmed:
        raise ValueError(
            "Payments exceed the final purchase cost. Confirm the overpayment to continue."
        )