import unittest
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from app.schemas.enums import ContactRoleEnum, ProductType
from app.services.chicken_purchase_options_service import ChickenPurchaseOptionsService


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


class FakeContactRepository:
    def __init__(self, contacts):
        self.contacts = contacts

    async def list_by_farm(self, farm_id):
        return self.contacts


class FakeBlockRepository:
    def __init__(self, blocks):
        self.blocks = blocks

    async def list_by_farm(self, farm_id, is_active):
        return [block for block in self.blocks if block.is_active == is_active]


class FakeChickenBatchRepository:
    def __init__(self, batches):
        self.batches = batches

    async def list_by_farm(self, farm_id, status):
        return self.batches


class FakeBatchBlockRepository:
    def __init__(self, quantities):
        self.quantities = quantities

    async def get_total_quantities_by_blocks(self, block_ids):
        return {
            block_id: quantity
            for block_id, quantity in self.quantities.items()
            if block_id in block_ids
        }


class ChickenPurchaseOptionsServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_options_filter_chicken_products_and_suppliers_and_include_stock(self):
        farm_id = uuid4()
        owner_id = uuid4()
        unit_id = uuid4()
        chicken_product = SimpleNamespace(
            id=uuid4(),
            farm_id=farm_id,
            name="Day-old chicks",
            product_type=ProductType.CHICKENS,
            description=None,
            is_active=True,
            is_sellable=False,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            product_units=[
                SimpleNamespace(
                    id=uuid4(),
                    unit_id=unit_id,
                    unit=SimpleNamespace(name="crate", abbreviation="crt"),
                    conversion_factor=Decimal("50"),
                    is_base_unit=False,
                )
            ],
        )
        inactive_product = SimpleNamespace(
            **{**chicken_product.__dict__, "id": uuid4(), "is_active": False}
        )
        feed_product = SimpleNamespace(
            **{**chicken_product.__dict__, "id": uuid4(), "product_type": ProductType.FEED}
        )
        supplier = SimpleNamespace(
            id=uuid4(),
            farm_id=farm_id,
            name="Hatchery",
            contact_roles=[SimpleNamespace(role=ContactRoleEnum.SUPPLIER)],
            phone=None,
            email=None,
            address=None,
            notes=None,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        customer = SimpleNamespace(
            **{
                **supplier.__dict__,
                "id": uuid4(),
                "name": "Customer",
                "contact_roles": [SimpleNamespace(role=ContactRoleEnum.CUSTOMER)],
            }
        )
        block = SimpleNamespace(
            id=uuid4(),
            name="Brooder A",
            capacity=100,
            over_capacity_limit=20,
            is_active=True,
        )
        inactive_block = SimpleNamespace(
            **{**block.__dict__, "id": uuid4(), "is_active": False}
        )
        batch = SimpleNamespace(
            id=uuid4(),
            name="2026 October 12 Batch 1",
            chicken_type="layers",
            hatch_date=None,
        )
        service = ChickenPurchaseOptionsService(
            product_repository=FakeProductRepository(
                [chicken_product, inactive_product, feed_product]
            ),
            contact_repository=FakeContactRepository([supplier, customer]),
            block_repository=FakeBlockRepository([block, inactive_block]),
            chicken_batch_repository=FakeChickenBatchRepository([batch]),
            batch_block_repository=FakeBatchBlockRepository({block.id: 85}),
            unit_of_work=FakeUnitOfWork(),
        )

        options = await service.get_options(
            SimpleNamespace(id=farm_id, owner_id=owner_id)
        )

        self.assertEqual([product.id for product in options.products], [chicken_product.id])
        self.assertEqual(options.products[0].product_units[0].conversion_factor, Decimal("50"))
        self.assertFalse(options.products[0].is_sellable)
        self.assertEqual([contact.id for contact in options.suppliers], [supplier.id])
        self.assertEqual(options.blocks[0].current_chickens, 85)
        self.assertEqual(options.blocks[0].maximum_chickens, 120)
        self.assertEqual(options.blocks[0].available_capacity, 35)
        self.assertEqual(options.batches[0].id, batch.id)
        self.assertEqual(options.batches[0].name, batch.name)


if __name__ == "__main__":
    unittest.main()
