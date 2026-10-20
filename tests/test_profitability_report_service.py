import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from app.services.profitability_report_service import (
    _replay_inventory,
    egg_available_quantity,
    net_profit,
    net_revenue,
    operating_expense_total,
)


def movement(
    product_id,
    quantity_delta,
    unit_cost,
    *,
    movement_type="receipt",
    source_type=None,
    source_id=None,
    source_item_id=None,
    day=1,
):
    return SimpleNamespace(
        id=uuid4(),
        product_id=product_id,
        quantity_delta=Decimal(quantity_delta),
        unit_cost=Decimal(unit_cost) if unit_cost is not None else None,
        movement_type=movement_type,
        source_type=source_type,
        source_id=source_id,
        source_item_id=source_item_id,
        occurred_on=date(2026, 1, day),
        created_at=datetime(2026, 1, day, tzinfo=timezone.utc),
    )


class ProfitabilityReportFormulaTests(unittest.TestCase):
    def test_egg_stock_reconciles_collection_losses_sales_and_delivered_returns(self):
        self.assertEqual(
            egg_available_quantity(
                Decimal("100"),
                Decimal("4"),
                Decimal("60"),
                Decimal("3"),
            ),
            Decimal("39"),
        )
        self.assertEqual(
            egg_available_quantity(
                Decimal("10"),
                Decimal("0"),
                Decimal("15"),
                Decimal("0"),
            ),
            Decimal("0"),
        )

    def test_moving_weighted_average_values_sales_and_closing_stock(self):
        product_id = uuid4()
        first_receipt = movement(product_id, "10", "2")
        second_receipt = movement(product_id, "10", "4", day=2)
        sale = movement(
            product_id,
            "-5",
            None,
            movement_type="sale",
            day=3,
        )

        costs, stock = _replay_inventory([first_receipt, second_receipt, sale])

        self.assertEqual(costs[sale.id], Decimal("3"))
        self.assertEqual(stock[product_id]["quantity"], Decimal("15"))
        self.assertEqual(stock[product_id]["valued_cost"], Decimal("45"))
        self.assertEqual(stock[product_id]["unvalued_quantity"], Decimal("0"))

    def test_unvalued_opening_stock_is_not_given_an_invented_cost(self):
        product_id = uuid4()
        opening = movement(product_id, "2", None, movement_type="opening_balance")
        receipt = movement(product_id, "3", "4", day=2)
        sale = movement(product_id, "-1", None, movement_type="sale", day=3)

        costs, stock = _replay_inventory([opening, receipt, sale])

        self.assertIsNone(costs[sale.id])
        self.assertEqual(stock[product_id]["unvalued_quantity"], Decimal("1"))
        self.assertEqual(stock[product_id]["valued_quantity"], Decimal("3"))
        self.assertEqual(stock[product_id]["valued_cost"], Decimal("12"))

    def test_valuation_event_costs_existing_stock_without_changing_quantity(self):
        product_id = uuid4()
        opening = movement(
            product_id,
            "4",
            None,
            movement_type="opening_balance",
        )
        valuation = movement(
            product_id,
            "0",
            "2.5",
            movement_type="valuation",
            day=2,
        )
        sale = movement(
            product_id,
            "-1",
            None,
            movement_type="sale",
            day=3,
        )

        costs, stock = _replay_inventory([opening, valuation, sale])

        self.assertEqual(costs[sale.id], Decimal("2.5"))
        self.assertEqual(stock[product_id]["quantity"], Decimal("3"))
        self.assertEqual(stock[product_id]["valued_cost"], Decimal("7.5"))
        self.assertEqual(stock[product_id]["unvalued_quantity"], Decimal("0"))

    def test_delivered_sale_return_reinstates_original_cost(self):
        product_id = uuid4()
        transaction_item_id = uuid4()
        return_item_id = uuid4()
        receipt = movement(product_id, "10", "3")
        sale = movement(
            product_id,
            "-4",
            None,
            movement_type="sale",
            source_type="transaction",
            source_item_id=transaction_item_id,
            day=2,
        )
        returned = movement(
            product_id,
            "2",
            None,
            movement_type="customer_return",
            source_type="sale_return",
            source_item_id=return_item_id,
            day=3,
        )

        _, stock = _replay_inventory(
            [receipt, sale, returned],
            sale_return_items={return_item_id: transaction_item_id},
        )

        self.assertEqual(stock[product_id]["quantity"], Decimal("8"))
        self.assertEqual(stock[product_id]["valued_cost"], Decimal("24"))

    def test_sale_credits_reduce_accrual_revenue_but_cash_refunds_do_not(self):
        gross_sales = Decimal("100")
        delivered_return_credit = Decimal("20")
        cash_refund = Decimal("15")

        reported_revenue = net_revenue(gross_sales, delivered_return_credit)

        self.assertEqual(reported_revenue, Decimal("80"))
        self.assertNotEqual(reported_revenue, gross_sales - delivered_return_credit - cash_refund)

    def test_incomplete_stock_prevents_a_claim_of_net_profit(self):
        self.assertIsNone(
            net_profit(
                Decimal("100"),
                Decimal("25"),
                Decimal("10"),
                Decimal("5"),
                complete=False,
            )
        )
        self.assertEqual(
            net_profit(
                Decimal("100"),
                Decimal("25"),
                Decimal("10"),
                Decimal("5"),
                complete=True,
            ),
            Decimal("60"),
        )

    def test_purchase_linked_expense_is_not_counted_again_as_an_expense(self):
        expenses = [
            SimpleNamespace(
                amount=Decimal("40"),
                canceled_at=None,
                purchase_transaction_id=uuid4(),
            ),
            SimpleNamespace(
                amount=Decimal("15"),
                canceled_at=None,
                purchase_transaction_id=None,
            ),
        ]

        self.assertEqual(
            operating_expense_total(expenses),
            Decimal("15"),
        )


if __name__ == "__main__":
    unittest.main()
