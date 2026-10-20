import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from app.core.exceptions import ConflictError
from app.schemas.enums import ProductType
from app.schemas.inventory import InventoryPurchaseItemRequest, InventoryPurchaseRequest
from app.services.inventory_purchase_service import InventoryPurchaseService


class FakeProductRepository:
    def __init__(self, product):
        self.product = product

    async def get_by_id(self, farm_id, product_id):
        if farm_id == self.product.farm_id and product_id == self.product.id:
            return self.product
        return None


class FakeTransactionService:
    def __init__(self):
        self.calls = []

    async def create_transaction(self, farm_id, transaction, user_id):
        self.calls.append((farm_id, transaction, user_id))
        return transaction


class InventoryPurchaseServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.farm_id = uuid4()
        self.user_id = uuid4()
        self.product = SimpleNamespace(
            id=uuid4(),
            farm_id=self.farm_id,
            is_active=True,
            product_type=ProductType.FEED,
        )
        self.transactions = FakeTransactionService()
        self.service = InventoryPurchaseService(
            product_repository=FakeProductRepository(self.product),
            transaction_service=self.transactions,
        )

    def request(self):
        return InventoryPurchaseRequest(
            transaction_date=date(2026, 10, 19),
            items=[
                InventoryPurchaseItemRequest(
                    product_id=self.product.id,
                    unit_id=uuid4(),
                    quantity=Decimal("2"),
                    unit_price=Decimal("15.00"),
                )
            ],
        )

    async def test_creates_purchase_transaction_for_inventory_product(self):
        transaction = await self.service.create_purchase(
            self.farm_id,
            self.request(),
            self.user_id,
        )

        self.assertEqual(transaction.transaction_type, "purchase")
        self.assertEqual(transaction.status, "completed")
        self.assertEqual(transaction.items[0].product_id, self.product.id)
        self.assertEqual(self.transactions.calls[0][2], self.user_id)

    async def test_rejects_chicken_and_egg_products(self):
        for product_type in (ProductType.CHICKENS, ProductType.EGGS):
            with self.subTest(product_type=product_type):
                self.product.product_type = product_type
                with self.assertRaises(ConflictError):
                    await self.service.create_purchase(self.farm_id, self.request())

        self.assertEqual(self.transactions.calls, [])


if __name__ == "__main__":
    unittest.main()
