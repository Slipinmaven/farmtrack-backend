import unittest
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from app.schemas.enums import ProductType
from app.services.chicken_sale_options_service import ChickenSaleOptionsService


class FakeUnitOfWork:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False


class FakeProductRepository:
    def __init__(self, products):
        self.products = products

    async def list_by_farm(self, farm_id):
        return self.products


class FakeBlockRepository:
    async def list_by_farm(self, farm_id, is_active):
        return []


class FakeChickenBatchRepository:
    async def list_by_farm(self, farm_id, status):
        return []

    async def get_estimated_purchase_unit_costs(self, farm_id, batch_ids):
        return {}


class FakeBatchBlockRepository:
    async def get_total_quantities_by_blocks(self, block_ids):
        return {}


class ChickenSaleOptionsServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_sale_options_exclude_products_not_marked_sellable(self):
        farm_id = uuid4()
        now = datetime.now()
        sellable_product = SimpleNamespace(
            id=uuid4(),
            farm_id=farm_id,
            name="Layers",
            product_type=ProductType.CHICKENS,
            description=None,
            is_active=True,
            is_sellable=True,
            created_at=now,
            updated_at=now,
            product_units=[],
        )
        farm_use_product = SimpleNamespace(
            **{
                **sellable_product.__dict__,
                "id": uuid4(),
                "name": "Replacement pullets",
                "is_sellable": False,
            }
        )
        service = ChickenSaleOptionsService(
            product_repository=FakeProductRepository(
                [sellable_product, farm_use_product]
            ),
            block_repository=FakeBlockRepository(),
            chicken_batch_repository=FakeChickenBatchRepository(),
            batch_block_repository=FakeBatchBlockRepository(),
            unit_of_work=FakeUnitOfWork(),
        )

        result = await service.get_options(
            SimpleNamespace(id=farm_id, owner_id=uuid4())
        )

        self.assertEqual([product.id for product in result.products], [sellable_product.id])
        self.assertTrue(result.products[0].is_sellable)


if __name__ == "__main__":
    unittest.main()
