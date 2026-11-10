import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from app.core.exceptions import ConflictError
from app.models.egg_production_cost_confirmations import EggProductionCostConfirmation
from app.schemas.profitability_report import (
    EggProductionCostConfirmationRequest,
    EggStockReconciliationResponse,
)
from app.services.profitability_report_service import (
    ProfitabilityReportService,
    _egg_sale_quantity_deducted_as_of,
    _product_margin_values,
    _replay_inventory,
    _reserved_egg_quantity,
    _requires_direct_sale_inventory_movement,
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


class FakeScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeSession:
    def __init__(self, results):
        self.results = iter(results)
        self.added = []

    async def execute(self, _statement):
        return FakeScalarResult(next(self.results))

    def add(self, value):
        self.added.append(value)


class FakeUnitOfWork:
    def __init__(self):
        self.commit = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False


class ProfitabilityReportFormulaTests(unittest.TestCase):
    def test_undelivered_fulfillment_egg_sale_does_not_reduce_physical_stock(self):
        self.assertEqual(
            _egg_sale_quantity_deducted_as_of(
                Decimal("5"),
                Decimal("30"),
                fulfillment_required=True,
                delivered_quantity=Decimal("0"),
            ),
            Decimal("0"),
        )

    def test_partially_delivered_fulfillment_egg_sale_reduces_stock_by_delivery(self):
        self.assertEqual(
            _egg_sale_quantity_deducted_as_of(
                Decimal("5"),
                Decimal("30"),
                fulfillment_required=True,
                delivered_quantity=Decimal("60"),
            ),
            Decimal("60"),
        )

    def test_legacy_immediate_egg_sale_reduces_stock_by_ordered_quantity(self):
        self.assertEqual(
            _egg_sale_quantity_deducted_as_of(
                Decimal("5"),
                Decimal("30"),
                fulfillment_required=False,
                delivered_quantity=Decimal("0"),
            ),
            Decimal("150"),
        )

    def test_fulfillment_egg_sale_does_not_require_movement_until_delivery(self):
        self.assertFalse(
            _requires_direct_sale_inventory_movement(
                "eggs",
                fulfillment_required=True,
            )
        )
        self.assertTrue(
            _requires_direct_sale_inventory_movement(
                "eggs",
                fulfillment_required=False,
            )
        )
        self.assertTrue(
            _requires_direct_sale_inventory_movement(
                "feed",
                fulfillment_required=True,
            )
        )

    def test_reserved_egg_quantity_accounts_for_partial_delivery(self):
        self.assertEqual(
            _reserved_egg_quantity(Decimal("150"), Decimal("60")),
            Decimal("90"),
        )
        self.assertEqual(
            _reserved_egg_quantity(
                Decimal("150"),
                Decimal("60"),
                Decimal("30"),
            ),
            Decimal("60"),
        )
        self.assertEqual(
            _reserved_egg_quantity(Decimal("150"), Decimal("150")),
            Decimal("0"),
        )

    def test_egg_stock_reconciliation_response_keeps_signed_difference(self):
        response = EggStockReconciliationResponse(
            product_id=uuid4(),
            product_name="Grade A eggs",
            unit_name="egg",
            unit_abbreviation="pcs",
            supported_quantity=Decimal("120"),
            ledger_quantity=Decimal("115"),
            difference=Decimal("5"),
        )

        self.assertEqual(
            response.difference,
            response.supported_quantity - response.ledger_quantity,
        )

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

    def test_estimated_valuation_precedes_same_day_sale_and_costs_it(self):
        product_id = uuid4()
        opening = movement(
            product_id,
            "4",
            None,
            movement_type="opening_balance",
            day=1,
        )
        sale = movement(
            product_id,
            "-2",
            None,
            movement_type="sale",
            day=2,
        )
        estimate = movement(
            product_id,
            "0",
            "3.25",
            movement_type="valuation",
            source_type="estimated_stock_valuation",
            day=2,
        )

        costs, stock = _replay_inventory([opening, sale, estimate])

        self.assertEqual(costs[sale.id], Decimal("3.25"))
        self.assertEqual(stock[product_id]["quantity"], Decimal("2"))
        self.assertEqual(stock[product_id]["valued_cost"], Decimal("6.50"))
        self.assertEqual(stock[product_id]["unvalued_quantity"], Decimal("0"))

    def test_estimated_valuation_costs_same_day_consumption_and_loss(self):
        product_id = uuid4()
        opening = movement(
            product_id,
            "5",
            None,
            movement_type="opening_balance",
            day=1,
        )
        consumption = movement(
            product_id,
            "-2",
            None,
            movement_type="consumption",
            day=2,
        )
        loss = movement(
            product_id,
            "-1",
            None,
            movement_type="loss",
            day=2,
        )
        estimate = movement(
            product_id,
            "0",
            "4",
            movement_type="valuation",
            source_type="estimated_stock_valuation",
            day=2,
        )

        costs, stock = _replay_inventory([opening, consumption, loss, estimate])

        self.assertEqual(costs[consumption.id], Decimal("4"))
        self.assertEqual(costs[loss.id], Decimal("4"))
        self.assertEqual(stock[product_id]["quantity"], Decimal("2"))
        self.assertEqual(stock[product_id]["valued_cost"], Decimal("8"))
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

    def test_product_margin_uses_sales_credits_and_stock_cost(self):
        self.assertEqual(
            _product_margin_values(
                Decimal("10"),
                Decimal("150"),
                Decimal("10"),
                Decimal("80"),
                Decimal("0"),
            ),
            (
                Decimal("140.00"),
                Decimal("15.00"),
                Decimal("8.00"),
                Decimal("60.00"),
            ),
        )

    def test_product_margin_is_unverified_when_any_sold_stock_has_no_cost(self):
        net_sales, average_price, average_cost, gross_profit = _product_margin_values(
            Decimal("10"),
            Decimal("150"),
            Decimal("0"),
            Decimal("80"),
            Decimal("2"),
        )

        self.assertEqual(net_sales, Decimal("150.00"))
        self.assertEqual(average_price, Decimal("15.00"))
        self.assertIsNone(average_cost)
        self.assertIsNone(gross_profit)

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


class EggProductionCostConfirmationTests(unittest.IsolatedAsyncioTestCase):
    async def test_confirmation_records_zero_cost_without_inventory_movement(self):
        session = FakeSession([uuid4(), None, None])
        unit_of_work = FakeUnitOfWork()
        service = ProfitabilityReportService(
            session=session,
            unit_of_work=unit_of_work,
            activity_service=SimpleNamespace(),
        )
        farm_id = uuid4()
        user_id = uuid4()
        from_date = date(2026, 11, 1)
        to_date = date(2026, 11, 4)

        result = await service.confirm_zero_egg_production_cost(
            farm_id,
            user_id=user_id,
            from_date=from_date,
            to_date=to_date,
        )

        self.assertTrue(result.confirmed)
        self.assertEqual(len(session.added), 1)
        confirmation = session.added[0]
        self.assertIsInstance(confirmation, EggProductionCostConfirmation)
        self.assertEqual(confirmation.farm_id, farm_id)
        self.assertEqual(confirmation.confirmed_by, user_id)
        self.assertEqual(confirmation.from_date, from_date)
        self.assertEqual(confirmation.to_date, to_date)
        unit_of_work.commit.assert_awaited_once()

    async def test_zero_cost_confirmation_is_rejected_when_product_use_exists(self):
        service = ProfitabilityReportService(
            session=FakeSession([uuid4(), uuid4()]),
            unit_of_work=FakeUnitOfWork(),
            activity_service=SimpleNamespace(),
        )

        with self.assertRaisesRegex(ConflictError, "Product use is recorded"):
            await service.confirm_zero_egg_production_cost(
                uuid4(),
                user_id=uuid4(),
                from_date=date(2026, 11, 1),
                to_date=date(2026, 11, 4),
            )

    def test_confirmation_request_requires_valid_date_order(self):
        with self.assertRaises(ValueError):
            EggProductionCostConfirmationRequest(
                from_date=date(2026, 11, 5),
                to_date=date(2026, 11, 4),
            )


if __name__ == "__main__":
    unittest.main()
