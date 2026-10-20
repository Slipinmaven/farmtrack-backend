import asyncio
import unittest
from datetime import date
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.repositories.transaction_reference_counter_repository import (
    TransactionReferenceCounterRepository,
)


class Result:
    def scalar_one(self) -> int:
        return 7


class Session:
    statement = None

    async def execute(self, statement):
        self.statement = statement
        return Result()


class TransactionReferenceCounterRepositoryTests(unittest.TestCase):
    def test_counter_allocation_uses_atomic_postgresql_upsert(self):
        session = Session()
        repository = TransactionReferenceCounterRepository(session)

        number = asyncio.run(
            repository.allocate_next_number(
                uuid4(),
                "sale",
                date(2026, 10, 12),
            )
        )

        sql = str(session.statement.compile(dialect=postgresql.dialect()))
        self.assertEqual(number, 7)
        self.assertIn("ON CONFLICT ON CONSTRAINT uq_transaction_reference_counters_scope", sql)
        self.assertIn("DO UPDATE SET last_number", sql)
        self.assertIn("RETURNING transaction_reference_counters.last_number", sql)