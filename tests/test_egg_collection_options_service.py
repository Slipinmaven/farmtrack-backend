import unittest
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

from app.schemas.enums import InventoryMovementType, ProductType
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
    def __init__(self, totals, collected_totals=None, opening_stock_totals=None):
        self.totals = totals
        self.collected_totals = collected_totals or totals
        self.opening_stock_totals = opening_stock_totals or {}

    async def get_totals_by_farm(self, farm_id):
        return self.totals

    async def get_collected_totals_by_farm(self, farm_id):
        return self.collected_totals

    async def get_opening_stock_totals_by_farm(self, farm_id):
        return self.opening_stock_totals


class FakeSoldTotalsRepository(FakeTotalsRepository):
    def __init__(self, totals, reserved_totals=None):
        super().__init__(totals)
        self.reserved_totals = reserved_totals or {}

    async def get_sold_base_quantities_by_farm(self, farm_id):
        return self.totals

    async def get_reserved_base_quantities_by_farm(self, farm_id, product_ids):
        return {
            product_id: quantity
            for product_id, quantity in self.reserved_totals.items()
            if product_id in product_ids
        }


class FakeInventoryMovementRepository:
    def __init__(self, totals=None):
        self.totals = totals or {}

    async def get_totals_by_type(self, farm_id, movement_type):
        return self.totals.get(movement_type, {})


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
                    {product_id: Decimal("50.000")},
                ),
            ),
            loss_repository=cast(
                Any,
                FakeTotalsRepository({product_id: Decimal("27.000")}),
            ),
            transaction_item_repository=cast(
                Any,
                FakeSoldTotalsRepository(
                    {product_id: Decimal("15.000")},
                    {product_id: Decimal("15.000")},
                ),
            ),
            inventory_movement_repository=cast(
                Any,
                FakeInventoryMovementRepository(),
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
            options.products[0].opening_stock_quantity_in_base_unit,
            Decimal("50.000"),
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
        self.assertEqual(
            options.products[0].reserved_quantity_in_base_unit,
            Decimal("15.000"),
        )
        self.assertEqual(
            options.products[0].on_hand_quantity_in_base_unit,
            Decimal("123.000"),
        )

    async def test_available_stock_includes_settlement_receipts_and_issues(self):
        farm_id = uuid4()
        product_id = uuid4()
        product = SimpleNamespace(
            id=product_id,
            name="Table eggs",
            product_type=ProductType.EGGS,
            is_active=True,
            is_sellable=True,
            product_units=[],
        )
        service = EggCollectionOptionsService(
            product_repository=cast(Any, FakeProductRepository([product])),
            block_repository=cast(Any, FakeBlockRepository()),
            collection_repository=cast(
                Any,
                FakeTotalsRepository({product_id: Decimal("100.000")}),
            ),
            loss_repository=cast(Any, FakeTotalsRepository({})),
            transaction_item_repository=cast(
                Any,
                FakeSoldTotalsRepository({}),
            ),
            inventory_movement_repository=cast(
                Any,
                FakeInventoryMovementRepository(
                    {
                        InventoryMovementType.SETTLEMENT_RECEIVED: {
                            product_id: Decimal("20.000")
                        },
                        InventoryMovementType.SETTLEMENT_ISSUED: {
                            product_id: Decimal("-35.000")
                        },
                    }
                ),
            ),
            unit_of_work=cast(Any, FakeUnitOfWork()),
        )

        options = await service.get_options(
            SimpleNamespace(id=farm_id, owner_id=uuid4())
        )

        self.assertEqual(
            options.products[0].available_quantity_in_base_unit,
            Decimal("85.000"),
        )
        self.assertEqual(
            options.products[0].stock_adjustment_quantity_in_base_unit,
            Decimal("-15.000"),
        )


if __name__ == "__main__":
    unittest.main()
