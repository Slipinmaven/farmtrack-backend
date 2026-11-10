import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

from pydantic import ValidationError

from app.core.unit_of_work import UnitOfWork
from app.repositories.transaction_repository import TransactionRepository
from app.schemas.enums import PaymentMethod, TransactionStatus, TransactionType
from app.schemas.receipt_history import ReceiptHistoryFilters
from app.services.receipt_history_service import ReceiptHistoryService


class FakeUnitOfWork:
    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc_value, _traceback):
        return False


class ReceiptHistoryServiceTests(unittest.IsolatedAsyncioTestCase):
    def test_receipt_history_rejects_reversed_date_range(self):
        with self.assertRaises(ValidationError):
            ReceiptHistoryFilters(
                from_date=date(2026, 11, 10),
                to_date=date(2026, 11, 1),
            )

    async def test_history_includes_transaction_and_individual_payment_details(self):
        transaction_id = uuid4()
        first_payment_id = uuid4()
        second_payment_id = uuid4()
        transaction = SimpleNamespace(
            id=transaction_id,
            transaction_type=TransactionType.SALE,
            status=TransactionStatus.COMPLETED,
            transaction_date=date(2026, 11, 1),
            reference_number="SALE-001",
            contact=SimpleNamespace(name="Customer One"),
            items=[
                SimpleNamespace(
                    total_amount=Decimal("125.00"),
                    product=SimpleNamespace(name="Layers"),
                ),
                SimpleNamespace(
                    total_amount=Decimal("25.00"),
                    product=SimpleNamespace(name="Feed"),
                ),
            ],
            payments=[
                SimpleNamespace(
                    id=first_payment_id,
                    payment_date=date(2026, 11, 1),
                    reference_number="MPESA-1",
                    amount=Decimal("50.00"),
                    payment_method=PaymentMethod.MPESA,
                ),
                SimpleNamespace(
                    id=second_payment_id,
                    payment_date=date(2026, 11, 2),
                    reference_number=None,
                    amount=Decimal("25.00"),
                    payment_method=PaymentMethod.CASH,
                ),
            ],
        )
        repository = SimpleNamespace(
            get_receipt_history=AsyncMock(
                return_value=([transaction], 1, Decimal("150.00"))
            )
        )
        service = ReceiptHistoryService(
            transaction_repository=cast(TransactionRepository, repository),
            unit_of_work=cast(UnitOfWork, FakeUnitOfWork()),
        )

        result = await service.get_history(
            uuid4(),
            ReceiptHistoryFilters(search="Customer One"),
            0,
            20,
        )

        self.assertEqual(result.total_count, 1)
        self.assertEqual(result.completed_total, Decimal("150.00"))
        self.assertEqual(result.items[0].transaction_total, Decimal("150.00"))
        self.assertEqual(result.items[0].product_names, ["Feed", "Layers"])
        self.assertEqual(result.items[0].payments[0].id, first_payment_id)
        self.assertEqual(result.items[0].payments[0].payment_number, 1)
        self.assertEqual(result.items[0].payments[1].payment_number, 2)


if __name__ == "__main__":
    unittest.main()
