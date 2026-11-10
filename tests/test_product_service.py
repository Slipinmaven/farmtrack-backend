import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from app.core.exceptions import ConflictError
from app.schemas.enums import ProductType
from app.schemas.product import ProductUpdateRequest
from app.services.product_service import ProductService


class FakeUnitOfWork:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False

    async def commit(self):
        pass


class ProductServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.farm = SimpleNamespace(id=uuid4(), owner_id=uuid4())
        self.product = SimpleNamespace(
            id=uuid4(),
            farm_id=self.farm.id,
            name="Layer chickens",
            product_type=ProductType.CHICKENS,
            description=None,
            is_active=True,
            is_sellable=True,
            product_units=[],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        self.repository = SimpleNamespace(
            get_by_id_for_update_with_units=AsyncMock(return_value=self.product),
            has_product_history=AsyncMock(return_value=True),
            update=AsyncMock(side_effect=self.update_product),
        )
        self.service = ProductService(self.repository, FakeUnitOfWork())

    async def update_product(self, product, product_data, unit_definitions):
        for field, value in product_data.items():
            setattr(product, field, value)
        return product

    async def test_cannot_change_product_type_after_stock_history_exists(self):
        request = ProductUpdateRequest(product_type=ProductType.EGGS)

        with self.assertRaisesRegex(ConflictError, "cannot be changed"):
            await self.service.update_product(
                self.farm,
                self.product.id,
                request,
            )

        self.assertEqual(self.product.product_type, ProductType.CHICKENS)
        self.repository.update.assert_not_awaited()

    async def test_can_change_product_type_before_product_is_used(self):
        self.repository.has_product_history.return_value = False
        request = ProductUpdateRequest(product_type=ProductType.EGGS)

        response = await self.service.update_product(
            self.farm,
            self.product.id,
            request,
        )

        self.assertEqual(response.product_type, ProductType.EGGS)
        self.repository.update.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
