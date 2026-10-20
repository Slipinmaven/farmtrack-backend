import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.repositories.product_repository import ProductRepository


class ProductRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_update_refreshes_database_generated_timestamp(self):
        product = SimpleNamespace(
            product_units=[],
            updated_at=datetime(2026, 10, 17, tzinfo=timezone.utc),
        )
        session = SimpleNamespace(
            flush=AsyncMock(),
            refresh=AsyncMock(),
        )
        repository = ProductRepository(session)

        updated = await repository.update(
            product,
            {"name": "Updated product"},
            None,
        )

        self.assertIs(updated, product)
        self.assertEqual(product.name, "Updated product")
        session.flush.assert_awaited_once()
        session.refresh.assert_awaited_once_with(
            product,
            attribute_names=["updated_at"],
        )


if __name__ == "__main__":
    unittest.main()
