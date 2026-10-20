import unittest
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from app.core.exceptions import ConflictError
from app.schemas.enums import InventoryMovementType, ProductType
from app.schemas.inventory import InventoryAdjustmentRequest
from app.services.inventory_service import InventoryService


class FakeUnitOfWork:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def commit(self):
        return None


class FakeProductRepository:
    def __init__(self, product):
        self.product = product

    async def get_by_id_for_update(self, farm_id, product_id):
        if farm_id == self.product.farm_id and product_id == self.product.id:
            return self.product
        return None


class FakeProductUnitRepository:
    def __init__(self, product_unit, base_unit):
        self.product_unit = product_unit
        self.base_unit = base_unit

    async def get_by_product_and_unit(self, product_id, unit_id):
        if (
            product_id == self.product_unit.product_id
            and unit_id == self.product_unit.unit_id
        ):
            return self.product_unit
        return None

    async def get_base_unit_for_product(self, product_id):
        return self.base_unit if product_id == self.product_unit.product_id else None


class FakeMovementRepository:
    def __init__(self):
        self.movements = []
        self.overview_query = None

    async def list_balances(self, farm_id):
        return []

    async def list_movements(self, farm_id, *, product_id=None, limit=100, offset=0):
        self.overview_query = (farm_id, product_id, limit, offset)
        return []

    async def has_movements(self, farm_id, product_id):
        return any(
            movement.farm_id == farm_id and movement.product_id == product_id
            for movement in self.movements
        )

    async def get_balance(self, farm_id, product_id):
        return sum(
            (
                movement.quantity_delta
                for movement in self.movements
                if movement.farm_id == farm_id
                and movement.product_id == product_id
            ),
            Decimal("0.000"),
        )

    async def create(self, **data):
        movement = SimpleNamespace(
            id=uuid4(),
            created_at=datetime.now(),
            **data,
        )
        self.movements.append(movement)
        return movement


class FakeActivityService:
    def __init__(self):
        self.events = []

    async def record(self, **event):
        self.events.append(event)


class InventoryServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.farm_id = uuid4()
        self.product_id = uuid4()
        self.unit_id = uuid4()
        self.base_unit_id = uuid4()
        self.user_id = uuid4()
        self.product = SimpleNamespace(
            id=self.product_id,
            farm_id=self.farm_id,
            name="Eggs",
            product_type=ProductType.FEED,
        )
        self.unit = SimpleNamespace(name="tray", abbreviation="tray")
        self.base_unit = SimpleNamespace(
            id=self.base_unit_id,
            name="egg",
            abbreviation="egg",
        )
        product_unit = SimpleNamespace(
            product_id=self.product_id,
            unit_id=self.unit_id,
            unit=self.unit,
            conversion_factor=Decimal("30"),
        )
        self.movements = FakeMovementRepository()
        self.activity = FakeActivityService()
        self.service = InventoryService(
            movement_repository=self.movements,
            product_repository=FakeProductRepository(self.product),
            product_unit_repository=FakeProductUnitRepository(
                product_unit,
                self.base_unit,
            ),
            unit_of_work=FakeUnitOfWork(),
            activity_service=self.activity,
        )
        self.farm = SimpleNamespace(id=self.farm_id, owner_id=self.user_id)

    def request(self, quantity=Decimal("2"), direction="in"):
        return InventoryAdjustmentRequest(
            product_id=self.product_id,
            unit_id=self.unit_id,
            quantity=quantity,
            direction=direction,
            occurred_on=date(2026, 10, 18),
            reason="Opening count",
        )

    async def test_opening_balance_converts_to_base_unit_and_is_audited(self):
        movement = await self.service.record_opening_balance(
            self.farm,
            self.request(),
        )

        self.assertEqual(movement.quantity_delta, Decimal("60.000"))
        self.assertEqual(movement.unit_name, "egg")
        self.assertEqual(movement.movement_type, InventoryMovementType.OPENING_BALANCE)
        self.assertEqual(len(self.activity.events), 1)

    async def test_overview_passes_movement_pagination_to_repository(self):
        await self.service.get_overview(
            self.farm,
            product_id=self.product_id,
            limit=200,
            offset=400,
        )

        self.assertEqual(
            self.movements.overview_query,
            (self.farm_id, self.product_id, 200, 400),
        )

    async def test_opening_balance_can_only_be_recorded_once(self):
        await self.service.record_opening_balance(self.farm, self.request())

        with self.assertRaises(ConflictError):
            await self.service.record_opening_balance(self.farm, self.request())

    async def test_outbound_adjustment_cannot_make_stock_negative(self):
        with self.assertRaises(ConflictError):
            await self.service.record_adjustment(
                self.farm,
                self.request(direction="out"),
            )

        self.assertEqual(self.movements.movements, [])

    async def test_manual_movements_reject_chickens_and_eggs(self):
        for product_type in (ProductType.CHICKENS, ProductType.EGGS):
            with self.subTest(product_type=product_type):
                self.product.product_type = product_type
                with self.assertRaisesRegex(
                    ConflictError,
                    "cannot be changed through generic inventory adjustments",
                ):
                    await self.service.record_opening_balance(
                        self.farm,
                        self.request(),
                    )
                self.assertEqual(self.movements.movements, [])
                self.assertEqual(self.activity.events, [])


if __name__ == "__main__":
    unittest.main()
