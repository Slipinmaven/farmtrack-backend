import unittest
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

from app.schemas.enums import ProductType
from app.services.egg_collection_options_service import EggCollectionOptionsService


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
    async def list_by_farm(self, farm_id, *, is_active):
        return []


class FakeTotalsRepository:
    def __init__(self, totals, collected_totals=None):
        self.totals = totals
        self.collected_totals = collected_totals or totals

    async def get_totals_by_farm(self, farm_id):
        return self.totals

    async def get_collected_totals_by_farm(self, farm_id):
        return self.collected_totals


class FakeSoldTotalsRepository(FakeTotalsRepository):
    async def get_sold_base_quantities_by_farm(self, farm_id):
        return self.totals


class EggCollectionOptionsServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_options_return_current_egg_stock_in_base_units(self):
        farm_id = uuid4()
        product_id = uuid4()
        unit_id = uuid4()
        product = SimpleNamespace(
            id=product_id,
            name="Table eggs",
            product_type=ProductType.EGGS,
            is_active=True,
            is_sellable=True,
            product_units=[
                SimpleNamespace(
                    unit_id=unit_id,
                    unit=SimpleNamespace(name="Piece", abbreviation="pc"),
                    conversion_factor=Decimal("1.000"),
                    is_base_unit=True,
                )
            ],
        )
        service = EggCollectionOptionsService(
            product_repository=cast(Any, FakeProductRepository([product])),
            block_repository=cast(Any, FakeBlockRepository()),
            collection_repository=cast(
                Any,
                FakeTotalsRepository(
                    {product_id: Decimal("150.000")},
                    {product_id: Decimal("100.000")},
                ),
            ),
            loss_repository=cast(
                Any,
                FakeTotalsRepository({product_id: Decimal("27.000")}),
            ),
            transaction_item_repository=cast(
                Any,
                FakeSoldTotalsRepository({product_id: Decimal("15.000")}),
            ),
            unit_of_work=cast(Any, FakeUnitOfWork()),
        )

        options = await service.get_options(
            SimpleNamespace(id=farm_id, owner_id=uuid4())
        )

        self.assertEqual(len(options.products), 1)
        self.assertEqual(
            options.products[0].collected_quantity_in_base_unit,
            Decimal("100.000"),
        )
        self.assertEqual(
            options.products[0].lost_quantity_in_base_unit,
            Decimal("27.000"),
        )
        self.assertEqual(
            options.products[0].sold_quantity_in_base_unit,
            Decimal("15.000"),
        )
        self.assertTrue(options.products[0].is_sellable)
        self.assertEqual(
            options.products[0].available_quantity_in_base_unit,
            Decimal("108.000"),
        )


if __name__ == "__main__":
    unittest.main()
