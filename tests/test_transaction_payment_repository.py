import unittest
from unittest.mock import AsyncMock, Mock

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError
from app.repositories.transaction_payment_repository import (
    TransactionPaymentRepository,
)


class TransactionPaymentRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_mpesa_reference_is_a_conflict(self):
        session = Mock()
        session.add = Mock()
        session.flush = AsyncMock(
            side_effect=IntegrityError(
                "insert",
                {},
                Exception(
                    "duplicate key violates uq_transaction_payments_mpesa_reference"
                ),
            )
        )
        repository = TransactionPaymentRepository(session)

        with self.assertRaisesRegex(
            ConflictError, "M-Pesa transaction reference has already been recorded"
        ):
            await repository.create(
                {
                    "transaction_id": "d3ff44a9-60a5-44bc-8cb9-819eed351a08",
                    "amount": "500.00",
                    "payment_date": "2026-11-05",
                    "payment_method": "mpesa",
                    "reference_number": "ABC123XYZ9",
                }
            )

    async def test_unrelated_integrity_errors_are_not_rewritten(self):
        session = Mock()
        session.add = Mock()
        session.flush = AsyncMock(
            side_effect=IntegrityError("insert", {}, Exception("other constraint"))
        )
        repository = TransactionPaymentRepository(session)

        with self.assertRaises(IntegrityError):
            await repository.create(
                {
                    "transaction_id": "d3ff44a9-60a5-44bc-8cb9-819eed351a08",
                    "amount": "500.00",
                    "payment_date": "2026-11-05",
                    "payment_method": "cash",
                }
            )


if __name__ == "__main__":
    unittest.main()
