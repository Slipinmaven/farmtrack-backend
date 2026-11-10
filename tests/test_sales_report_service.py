import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

from app.core.unit_of_work import UnitOfWork
from app.repositories.transaction_repository import TransactionRepository
from app.schemas.enums import ProductType, TransactionStatus, TransactionType
from app.schemas.sales_report import SalesReportFilters
from app.services.sales_report_service import SalesReportService


class FakeUnitOfWork:
    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc_value, _traceback):
        return False


class SalesReportServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_outstanding_balances_keep_all_account_totals(self):
        first_id = uuid4()
        second_id = uuid4()
        repository = SimpleNamespace(
            get_outstanding_balance_summary=AsyncMock(
                return_value=[
                    SimpleNamespace(
                        id=first_id,
                        transaction_type=TransactionType.SALE,
                        reference_number="SALE-001",
                        transaction_date=date(2026, 11, 1),
                        contact_name="Customer One",
                        balance_due=Decimal("70.00"),
                        credit_balance=Decimal("0.00"),
                        account_balance_due=Decimal("120.00"),
                        account_credit_balance=Decimal("0.00"),
                        customer_balance_due_total=Decimal("125.00"),
                        supplier_balance_due_total=Decimal("90.00"),
                        customer_credit_total=Decimal("15.00"),
                        supplier_credit_total=Decimal("5.00"),
                    ),
                    SimpleNamespace(
                        id=second_id,
                        transaction_type=TransactionType.PURCHASE,
                        reference_number="PUR-001",
                        transaction_date=date(2026, 11, 2),
                        contact_name="Supplier One",
                        balance_due=Decimal("90.00"),
                        credit_balance=Decimal("0.00"),
                        account_balance_due=Decimal("90.00"),
                        account_credit_balance=Decimal("0.00"),
                        customer_balance_due_total=Decimal("125.00"),
                        supplier_balance_due_total=Decimal("90.00"),
                        customer_credit_total=Decimal("15.00"),
                        supplier_credit_total=Decimal("5.00"),
                    ),
                ]
            )
        )
        service = SalesReportService(
            transaction_repository=cast(TransactionRepository, repository),
            unit_of_work=cast(UnitOfWork, FakeUnitOfWork()),
        )

        summary = await service.get_outstanding_balances(uuid4(), limit=20)

        self.assertEqual([item.id for item in summary.items], [first_id, second_id])
        self.assertEqual(summary.customer_balance_due_total, Decimal("125.00"))
        self.assertEqual(summary.supplier_balance_due_total, Decimal("90.00"))
        self.assertEqual(summary.customer_credit_total, Decimal("15.00"))
        self.assertEqual(summary.supplier_credit_total, Decimal("5.00"))

    async def test_pending_deliveries_include_only_outstanding_tracked_items(self):
        sale_id = uuid4()
        chicken_item_id = uuid4()
        egg_item_id = uuid4()
        chicken_product = SimpleNamespace(
            name="Layer chickens",
            product_type=ProductType.CHICKENS,
        )
        egg_product = SimpleNamespace(
            name="Table eggs",
            product_type=ProductType.EGGS,
        )
        transaction = SimpleNamespace(
            id=sale_id,
            reference_number="SAL-2026-001",
            transaction_date=date(2026, 11, 4),
            contact=SimpleNamespace(name="Customer One"),
            fulfillment_required=True,
            items=[
                SimpleNamespace(
                    id=chicken_item_id,
                    quantity=Decimal("10"),
                    conversion_factor=Decimal("1"),
                    product=chicken_product,
                    unit=SimpleNamespace(name="bird"),
                ),
                SimpleNamespace(
                    id=egg_item_id,
                    quantity=Decimal("3"),
                    conversion_factor=Decimal("30"),
                    product=egg_product,
                    unit=SimpleNamespace(name="tray"),
                ),
            ],
            sale_deliveries=[
                SimpleNamespace(
                    items=[
                        SimpleNamespace(
                            transaction_item_id=chicken_item_id,
                            quantity=Decimal("4"),
                        ),
                        SimpleNamespace(
                            transaction_item_id=egg_item_id,
                            quantity=Decimal("30"),
                        ),
                    ]
                )
            ],
            sale_returns=[
                SimpleNamespace(
                    return_type="undelivered_cancelled",
                    items=[
                        SimpleNamespace(
                            transaction_item_id=chicken_item_id,
                            quantity=Decimal("2"),
                        )
                    ],
                )
            ],
        )
        repository = SimpleNamespace(
            list_pending_sale_deliveries=AsyncMock(return_value=[transaction])
        )
        service = SalesReportService(
            transaction_repository=cast(TransactionRepository, repository),
            unit_of_work=cast(UnitOfWork, FakeUnitOfWork()),
        )

        pending = await service.get_pending_deliveries(uuid4(), limit=5)

        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].id, sale_id)
        self.assertEqual(pending[0].customer_name, "Customer One")
        self.assertEqual(
            [
                (
                    item.product_name,
                    item.quantity_remaining,
                    item.quantity_remaining_base,
                    item.unit_name,
                )
                for item in pending[0].items
            ],
            [
                ("Layer chickens", Decimal("4"), Decimal("4"), "bird"),
                ("Table eggs", Decimal("2"), Decimal("60"), "tray"),
            ],
        )

    async def test_pending_deliveries_skip_legacy_untracked_egg_sales(self):
        transaction = SimpleNamespace(
            id=uuid4(),
            reference_number="SAL-LEGACY",
            transaction_date=date(2026, 11, 4),
            contact=None,
            fulfillment_required=False,
            items=[
                SimpleNamespace(
                    id=uuid4(),
                    quantity=Decimal("2"),
                    conversion_factor=Decimal("30"),
                    product=SimpleNamespace(
                        name="Eggs",
                        product_type=ProductType.EGGS,
                    ),
                    unit=SimpleNamespace(name="tray"),
                )
            ],
            sale_deliveries=[],
            sale_returns=[],
        )
        repository = SimpleNamespace(
            list_pending_sale_deliveries=AsyncMock(return_value=[transaction])
        )
        service = SalesReportService(
            transaction_repository=cast(TransactionRepository, repository),
            unit_of_work=cast(UnitOfWork, FakeUnitOfWork()),
        )

        pending = await service.get_pending_deliveries(uuid4(), limit=5)

        self.assertEqual(pending, [])

    async def test_sale_balances_include_refunds_and_return_credits(self):
        transaction = SimpleNamespace(
            id=uuid4(),
            reference_number="SALE-001",
            transaction_date=date(2026, 10, 1),
            transaction_type=TransactionType.SALE,
            status=TransactionStatus.COMPLETED,
            contact=SimpleNamespace(name="Customer One"),
            items=[
                SimpleNamespace(
                    total_amount=Decimal("100.00"),
                    quantity=Decimal("2.00"),
                    product=SimpleNamespace(
                        name="Feed",
                        product_type=ProductType.FEED,
                    ),
                    unit=SimpleNamespace(name="bags"),
                )
            ],
            payments=[SimpleNamespace(amount=Decimal("80.00"))],
            refunds=[SimpleNamespace(amount=Decimal("20.00"))],
            sale_returns=[
                SimpleNamespace(
                    items=[SimpleNamespace(credit_amount=Decimal("30.00"))]
                )
            ],
        )
        repository = SimpleNamespace(
            get_sales_report=AsyncMock(
                return_value=(
                    [transaction],
                    1,
                    [ProductType.FEED],
                    [
                        (
                            "2026-10",
                            1,
                            Decimal("100.00"),
                            Decimal("60.00"),
                            Decimal("10.00"),
                            Decimal("30.00"),
                            Decimal("0.00"),
                            Decimal("0.00"),
                            Decimal("0.00"),
                            Decimal("30.00"),
                        )
                    ],
                    [
                        (
                            date(2026, 10, 1),
                            1,
                            Decimal("100.00"),
                        )
                    ],
                    (
                        1,
                        Decimal("100.00"),
                        Decimal("60.00"),
                        Decimal("10.00"),
                        Decimal("30.00"),
                        Decimal("0.00"),
                        Decimal("0.00"),
                        Decimal("0.00"),
                        Decimal("30.00"),
                    ),
                )
            )
        )
        service = SalesReportService(
            transaction_repository=cast(TransactionRepository, repository),
            unit_of_work=cast(UnitOfWork, FakeUnitOfWork()),
        )

        report = await service.get_report(
            uuid4(),
            SalesReportFilters(),
            0,
            20,
            include_daily=True,
        )

        self.assertEqual(report.items[0].amount_paid, Decimal("60.00"))
        self.assertEqual(report.items[0].balance_due, Decimal("10.00"))
        self.assertEqual(report.items[0].credit_balance, Decimal("0.00"))
        self.assertEqual(report.items[0].return_credits, Decimal("30.00"))
        self.assertEqual(report.items[0].goods_settlement, Decimal("0.00"))
        self.assertEqual(report.items[0].service_settlement, Decimal("0.00"))
        self.assertEqual(report.summary.amount_received, Decimal("60.00"))
        self.assertEqual(report.summary.balance_due, Decimal("10.00"))
        self.assertEqual(report.summary.return_credits, Decimal("30.00"))
        self.assertEqual(report.summary.goods_settlements, Decimal("0.00"))
        self.assertEqual(report.summary.service_settlements, Decimal("0.00"))
        self.assertEqual(report.summary.customer_credit, Decimal("0.00"))
        self.assertEqual(report.summary.unallocated_amount, Decimal("30.00"))
        self.assertEqual(report.summary.monthly[0].month, "2026-10")
        self.assertEqual(report.summary.monthly[0].amount_received, Decimal("60.00"))
        self.assertEqual(report.summary.monthly[0].balance_due, Decimal("10.00"))
        self.assertEqual(report.summary.monthly[0].return_credits, Decimal("30.00"))
        self.assertEqual(report.summary.monthly[0].goods_settlements, Decimal("0.00"))
        self.assertEqual(report.summary.monthly[0].service_settlements, Decimal("0.00"))
        self.assertEqual(report.summary.monthly[0].customer_credit, Decimal("0.00"))
        self.assertEqual(report.summary.monthly[0].unallocated_amount, Decimal("30.00"))
        self.assertEqual(report.sellable_categories, [ProductType.FEED])
        self.assertEqual(report.items[0].products_sold[0].quantity, Decimal("2.00"))
        self.assertEqual(report.items[0].products_sold[0].unit_name, "bags")
        self.assertEqual(report.daily[0].day, date(2026, 10, 1))
        self.assertEqual(report.daily[0].transaction_count, 1)
        self.assertEqual(report.daily[0].sales_total, Decimal("100.00"))


if __name__ == "__main__":
    unittest.main()
