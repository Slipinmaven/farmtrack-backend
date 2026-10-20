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
                    [],
                    [(date(2026, 10, 1), 1, Decimal("100.00"))],
                    (1, Decimal("100.00"), Decimal("80.00"), Decimal("10.00")),
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
        self.assertEqual(report.sellable_categories, [ProductType.FEED])
        self.assertEqual(report.items[0].products_sold[0].quantity, Decimal("2.00"))
        self.assertEqual(report.items[0].products_sold[0].unit_name, "bags")
        self.assertEqual(report.daily[0].day, date(2026, 10, 1))
        self.assertEqual(report.daily[0].transaction_count, 1)
        self.assertEqual(report.daily[0].sales_total, Decimal("100.00"))


if __name__ == "__main__":
    unittest.main()
