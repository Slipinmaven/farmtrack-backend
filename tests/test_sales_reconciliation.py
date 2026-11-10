import unittest
from datetime import date
from decimal import Decimal

from app.schemas.enums import TransactionStatus
from app.services.sales_reconciliation import (
    SalesReconciliationRecord,
    summarize_sales,
)


class SalesReconciliationTests(unittest.TestCase):
    def test_partial_payment_and_cash_settlement_reconcile(self):
        summary = summarize_sales(
            [
                SalesReconciliationRecord(
                    transaction_date=date(2026, 11, 4),
                    status=TransactionStatus.COMPLETED,
                    transaction_total=Decimal("250000.00"),
                    payments=Decimal("25000.00"),
                    refunds=Decimal("0.00"),
                    return_credits=Decimal("0.00"),
                    settlements=(
                        {
                            "direction": "contact_to_farm",
                            "total_value": Decimal("220000.00"),
                            "lines": [
                                {"kind": "cash", "amount": "220000.00"}
                            ],
                        },
                    ),
                ),
                SalesReconciliationRecord(
                    transaction_date=date(2026, 11, 4),
                    status=TransactionStatus.COMPLETED,
                    transaction_total=Decimal("100000.00"),
                    payments=Decimal("50000.00"),
                    refunds=Decimal("0.00"),
                    return_credits=Decimal("0.00"),
                ),
                SalesReconciliationRecord(
                    transaction_date=date(2026, 11, 4),
                    status=TransactionStatus.COMPLETED,
                    transaction_total=Decimal("4800.00"),
                    payments=Decimal("4800.00"),
                    refunds=Decimal("0.00"),
                    return_credits=Decimal("0.00"),
                ),
            ],
            from_date=date(2026, 11, 4),
            to_date=date(2026, 11, 4),
        )

        self.assertEqual(summary.sales_total, Decimal("354800.00"))
        self.assertEqual(summary.amount_received, Decimal("299800.00"))
        self.assertEqual(summary.balance_due, Decimal("55000.00"))
        self.assertEqual(summary.unallocated_amount, Decimal("0.00"))

    def test_returns_refunds_and_noncash_settlements_are_explicit_adjustments(self):
        summary = summarize_sales(
            [
                SalesReconciliationRecord(
                    transaction_date=date(2026, 11, 4),
                    status=TransactionStatus.COMPLETED,
                    transaction_total=Decimal("100.00"),
                    payments=Decimal("80.00"),
                    refunds=Decimal("20.00"),
                    return_credits=Decimal("10.00"),
                    settlements=(
                        {
                            "direction": "contact_to_farm",
                            "total_value": Decimal("20.00"),
                            "lines": [
                                {"kind": "goods", "value": "12.00"},
                                {"kind": "service", "value": "8.00"},
                            ],
                        },
                        {
                            "direction": "farm_to_contact",
                            "total_value": Decimal("5.00"),
                            "lines": [
                                {"kind": "goods", "value": "2.00"},
                                {"kind": "service", "value": "3.00"},
                            ],
                        },
                    ),
                )
            ],
            from_date=None,
            to_date=None,
        )

        self.assertEqual(summary.amount_received, Decimal("60.00"))
        self.assertEqual(summary.balance_due, Decimal("15.00"))
        self.assertEqual(summary.return_credits, Decimal("10.00"))
        self.assertEqual(summary.goods_settlements, Decimal("10.00"))
        self.assertEqual(summary.service_settlements, Decimal("5.00"))
        self.assertEqual(summary.customer_credit, Decimal("0.00"))
        self.assertEqual(summary.unallocated_amount, Decimal("25.00"))
        self.assertEqual(
            summary.sales_total,
            summary.amount_received
            + summary.balance_due
            + summary.return_credits
            + summary.goods_settlements
            + summary.service_settlements
            - summary.customer_credit,
        )

    def test_only_completed_sales_inside_inclusive_period_are_counted(self):
        records = [
            SalesReconciliationRecord(
                transaction_date=record_date,
                status=status,
                transaction_total=Decimal("10.00"),
                payments=Decimal("10.00"),
                refunds=Decimal("0.00"),
                return_credits=Decimal("0.00"),
            )
            for record_date, status in (
                (date(2026, 11, 3), TransactionStatus.COMPLETED),
                (date(2026, 11, 4), TransactionStatus.COMPLETED),
                (date(2026, 11, 5), TransactionStatus.COMPLETED),
                (date(2026, 11, 4), TransactionStatus.CANCELLED),
            )
        ]

        summary = summarize_sales(
            records,
            from_date=date(2026, 11, 4),
            to_date=date(2026, 11, 4),
        )

        self.assertEqual(summary.transaction_count, 1)
        self.assertEqual(summary.sales_total, Decimal("10.00"))
        self.assertEqual(summary.unallocated_amount, Decimal("0.00"))

    def test_pending_delivery_does_not_change_financial_reconciliation(self):
        summary = summarize_sales(
            [
                SalesReconciliationRecord(
                    transaction_date=date(2026, 11, 4),
                    status=TransactionStatus.COMPLETED,
                    transaction_total=Decimal("250.00"),
                    payments=Decimal("100.00"),
                    refunds=Decimal("0.00"),
                    return_credits=Decimal("0.00"),
                )
            ],
            from_date=date(2026, 11, 4),
            to_date=date(2026, 11, 4),
        )

        self.assertEqual(summary.amount_received, Decimal("100.00"))
        self.assertEqual(summary.balance_due, Decimal("150.00"))
        self.assertEqual(summary.return_credits, Decimal("0.00"))
        self.assertEqual(summary.goods_settlements, Decimal("0.00"))
        self.assertEqual(summary.service_settlements, Decimal("0.00"))
        self.assertEqual(summary.customer_credit, Decimal("0.00"))
        self.assertEqual(summary.unallocated_amount, Decimal("0.00"))

    def test_customer_overpayment_is_reported_as_credit_source(self):
        summary = summarize_sales(
            [
                SalesReconciliationRecord(
                    transaction_date=date(2026, 11, 4),
                    status=TransactionStatus.COMPLETED,
                    transaction_total=Decimal("900.00"),
                    payments=Decimal("1000.00"),
                    refunds=Decimal("0.00"),
                    return_credits=Decimal("0.00"),
                )
            ],
            from_date=None,
            to_date=None,
        )

        self.assertEqual(summary.amount_received, Decimal("1000.00"))
        self.assertEqual(summary.balance_due, Decimal("0.00"))
        self.assertEqual(summary.return_credits, Decimal("0.00"))
        self.assertEqual(summary.goods_settlements, Decimal("0.00"))
        self.assertEqual(summary.service_settlements, Decimal("0.00"))
        self.assertEqual(summary.customer_credit, Decimal("100.00"))
        self.assertEqual(summary.unallocated_amount, Decimal("-100.00"))

    def test_monthly_reconciliation_can_sum_to_the_selected_sales_summary(self):
        records = [
            SalesReconciliationRecord(
                transaction_date=date(2026, 11, 4),
                status=TransactionStatus.COMPLETED,
                transaction_total=Decimal("1000.00"),
                payments=Decimal("100.00"),
                refunds=Decimal("0.00"),
                return_credits=Decimal("0.00"),
                settlements=(
                    {
                        "direction": "contact_to_farm",
                        "total_value": Decimal("400.00"),
                        "lines": [{"kind": "cash", "amount": "400.00"}],
                    },
                ),
            ),
            SalesReconciliationRecord(
                transaction_date=date(2026, 12, 1),
                status=TransactionStatus.COMPLETED,
                transaction_total=Decimal("500.00"),
                payments=Decimal("600.00"),
                refunds=Decimal("0.00"),
                return_credits=Decimal("0.00"),
            ),
        ]
        overall = summarize_sales(records, from_date=None, to_date=None)
        monthly = [
            summarize_sales([record], from_date=None, to_date=None)
            for record in records
        ]

        self.assertEqual(
            sum((item.sales_total for item in monthly), Decimal("0.00")),
            overall.sales_total,
        )
        self.assertEqual(
            sum((item.amount_received for item in monthly), Decimal("0.00")),
            overall.amount_received,
        )
        self.assertEqual(
            sum((item.balance_due for item in monthly), Decimal("0.00")),
            overall.balance_due,
        )
        self.assertEqual(
            sum((item.unallocated_amount for item in monthly), Decimal("0.00")),
            overall.unallocated_amount,
        )


if __name__ == "__main__":
    unittest.main()
