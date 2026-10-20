import unittest
from decimal import Decimal

from app.services.transaction_pricing import (
    calculate_discount_allocation,
    validate_payment_confirmation,
)


class TransactionPricingTests(unittest.TestCase):
    def test_no_discount_preserves_all_line_subtotals(self):
        amount, lines = calculate_discount_allocation(
            [Decimal("120000.00")], None, Decimal("0.00")
        )

        self.assertEqual(amount, Decimal("0.00"))
        self.assertEqual(lines, [Decimal("0.00")])

    def test_fixed_discount_is_allocated_across_lines_to_the_cent(self):
        amount, lines = calculate_discount_allocation(
            [Decimal("60000.00"), Decimal("10000.00")],
            "fixed",
            Decimal("20000.00"),
        )

        self.assertEqual(amount, Decimal("20000.00"))
        self.assertEqual(lines, [Decimal("17142.86"), Decimal("2857.14")])
        self.assertEqual(sum(lines), amount)

    def test_percentage_discount_rounds_half_up_and_preserves_total(self):
        amount, lines = calculate_discount_allocation(
            [Decimal("0.05"), Decimal("0.05")],
            "percentage",
            Decimal("25.00"),
        )

        self.assertEqual(amount, Decimal("0.03"))
        self.assertEqual(sum(lines), amount)

    def test_full_discount_is_valid(self):
        amount, lines = calculate_discount_allocation(
            [Decimal("10.00"), Decimal("2.00")],
            "percentage",
            Decimal("100.00"),
        )

        self.assertEqual(amount, Decimal("12.00"))
        self.assertEqual(lines, [Decimal("10.00"), Decimal("2.00")])

    def test_discount_cannot_exceed_subtotal(self):
        with self.assertRaisesRegex(ValueError, "cannot exceed"):
            calculate_discount_allocation(
                [Decimal("10.00")], "fixed", Decimal("10.01")
            )

    def test_large_amounts_remain_exact(self):
        amount, lines = calculate_discount_allocation(
            [Decimal("999999999.99"), Decimal("0.01")],
            "fixed",
            Decimal("123456789.99"),
        )

        self.assertEqual(amount, Decimal("123456789.99"))
        self.assertEqual(sum(lines), amount)

    def test_payment_equal_to_final_cost_needs_no_confirmation(self):
        validate_payment_confirmation(
            Decimal("100.00"), [Decimal("100.00")], False
        )

    def test_payment_above_final_cost_requires_explicit_confirmation(self):
        with self.assertRaisesRegex(ValueError, "Confirm the overpayment"):
            validate_payment_confirmation(
                Decimal("100.00"), [Decimal("1000.00")], False
            )

    def test_confirmed_overpayment_is_allowed(self):
        validate_payment_confirmation(
            Decimal("100.00"), [Decimal("1000.00")], True
        )