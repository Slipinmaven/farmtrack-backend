import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from app.core.exceptions import ConflictError
from app.schemas.enums import InventoryMovementType, ProductType
from app.schemas.inventory_opening_setup import InventoryOpeningSetupRequest
from app.services.inventory_opening_setup_service import InventoryOpeningSetupService


class FakeUnitOfWork:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def commit(self):
        return None


class InventoryOpeningSetupServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.farm_id = uuid4()
        self.owner_id = uuid4()
        self.farm = SimpleNamespace(id=self.farm_id, owner_id=self.owner_id)
        self.block_id = uuid4()
        self.product_id = uuid4()
        self.unit_id = uuid4()
        self.batch_id = uuid4()
        self.farm_repository = SimpleNamespace(
            get_by_id_for_update=AsyncMock(return_value=self.farm)
        )
        self.setup_repository = SimpleNamespace(
            get_for_species=AsyncMock(return_value=None),
            create=AsyncMock(),
        )
        self.batch_repository = SimpleNamespace(
            list_by_farm=AsyncMock(return_value=[]),
            create=AsyncMock(return_value=SimpleNamespace(id=self.batch_id)),
        )
        self.batch_block_repository = SimpleNamespace(create=AsyncMock())
        self.block = SimpleNamespace(
            id=self.block_id,
            name="Layer house",
            is_active=True,
            capacity=20,
            over_capacity_limit=2,
        )
        self.block_repository = SimpleNamespace(
            get_by_id_for_update=AsyncMock(return_value=self.block),
            get_occupied_chickens=AsyncMock(return_value=0),
        )
        self.product = SimpleNamespace(
            id=self.product_id,
            name="Table eggs",
            is_active=True,
            product_type=ProductType.EGGS,
        )
        self.product_repository = SimpleNamespace(
            list_by_farm=AsyncMock(return_value=[]),
            get_by_id_for_update=AsyncMock(return_value=self.product),
            has_inventory_movements=AsyncMock(return_value=False),
        )
        self.product_unit = SimpleNamespace(
            unit_id=self.unit_id,
            conversion_factor=Decimal("30"),
        )
        self.product_unit_repository = SimpleNamespace(
            get_by_product_and_unit=AsyncMock(return_value=self.product_unit)
        )
        self.collections = []

        async def create_collections(farm_id, records):
            created = [
                SimpleNamespace(
                    id=uuid4(),
                    farm_id=farm_id,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                    **record,
                )
                for record in records
            ]
            self.collections.extend(created)
            return created

        self.collection_repository = SimpleNamespace(
            list_by_farm=AsyncMock(return_value=[]),
            create_many=AsyncMock(side_effect=create_collections),
        )
        self.inventory_service = SimpleNamespace(append_movement=AsyncMock())
        self.activity_service = SimpleNamespace(record=AsyncMock())
        self.service = InventoryOpeningSetupService(
            farm_repository=self.farm_repository,
            setup_repository=self.setup_repository,
            batch_repository=self.batch_repository,
            batch_block_repository=self.batch_block_repository,
            block_repository=self.block_repository,
            collection_repository=self.collection_repository,
            product_repository=self.product_repository,
            product_unit_repository=self.product_unit_repository,
            inventory_service=self.inventory_service,
            activity_service=self.activity_service,
            unit_of_work=FakeUnitOfWork(),
        )

    def request(self, species, **values):
        return InventoryOpeningSetupRequest.model_validate(
            {
                "species": species,
                "setup_date": "2026-10-20",
                **values,
            }
        )

    async def test_chicken_opening_stock_creates_batch_and_housing_allocation(self):
        request = self.request(
            "chickens",
            chicken_batches=[
                {
                    "name": "Opening layers",
                    "chicken_type": "layers",
                    "allocations": [
                        {"block_id": str(self.block_id), "quantity": 12}
                    ],
                }
            ],
        )

        result = await self.service.create(self.farm, request)

        self.assertEqual(result.record_count, 1)
        self.batch_repository.create.assert_awaited_once()
        self.batch_block_repository.create.assert_awaited_once_with(
            {
                "batch_id": self.batch_id,
                "block_id": self.block_id,
                "quantity": 12,
            }
        )
        self.setup_repository.create.assert_awaited_once_with(
            self.farm_id, "chickens", date(2026, 10, 20)
        )
        self.inventory_service.append_movement.assert_not_awaited()

    async def test_chicken_opening_stock_cannot_exceed_block_capacity(self):
        request = self.request(
            "chickens",
            chicken_batches=[
                {
                    "name": "Opening layers",
                    "chicken_type": "layers",
                    "allocations": [
                        {"block_id": str(self.block_id), "quantity": 23}
                    ],
                }
            ],
        )
        self.block.capacity = 20
        self.block.over_capacity_limit = 2

        with self.assertRaises(ConflictError):
            await self.service.create(self.farm, request)

        self.batch_repository.create.assert_not_awaited()
        self.setup_repository.create.assert_not_awaited()

    async def test_hatch_date_cannot_follow_opening_stock_date(self):
        request = self.request(
            "chickens",
            chicken_batches=[
                {
                    "name": "Opening layers",
                    "chicken_type": "layers",
                    "hatch_date": "2026-10-21",
                    "allocations": [
                        {"block_id": str(self.block_id), "quantity": 12}
                    ],
                }
            ],
        )

        with self.assertRaises(ConflictError):
            await self.service.create(self.farm, request)

        self.batch_repository.create.assert_not_awaited()

    async def test_egg_opening_stock_is_marked_and_added_to_inventory_ledger(self):
        request = self.request(
            "eggs",
            egg_stock=[
                {
                    "product_id": str(self.product_id),
                    "unit_id": str(self.unit_id),
                    "quantity": "2",
                }
            ],
        )

        result = await self.service.create(self.farm, request)

        self.assertEqual(result.record_count, 1)
        self.assertEqual(self.collections[0].entry_type, "opening_stock")
        self.assertIsNone(self.collections[0].block_id)
        self.inventory_service.append_movement.assert_awaited_once()
        movement = self.inventory_service.append_movement.await_args.kwargs
        self.assertEqual(movement["quantity_delta"], Decimal("60.000"))
        self.assertEqual(
            movement["movement_type"],
            InventoryMovementType.OPENING_BALANCE,
        )
        self.assertEqual(movement["source_type"], "egg_collection")

    async def test_egg_opening_stock_supports_multiple_units_without_a_block(self):
        base_unit_id = uuid4()
        unit_by_id = {
            self.unit_id: self.product_unit,
            base_unit_id: SimpleNamespace(
                unit_id=base_unit_id,
                conversion_factor=Decimal("1"),
            ),
        }
        self.product_unit_repository.get_by_product_and_unit = AsyncMock(
            side_effect=lambda _product_id, unit_id: unit_by_id[unit_id]
        )
        request = self.request(
            "eggs",
            egg_stock=[
                {
                    "product_id": str(self.product_id),
                    "unit_id": str(self.unit_id),
                    "quantity": "2",
                    "unit_cost": "600",
                },
                {
                    "product_id": str(self.product_id),
                    "unit_id": str(base_unit_id),
                    "quantity": "5",
                    "unit_cost": "10",
                },
            ],
        )

        result = await self.service.create(self.farm, request)

        self.assertEqual(result.record_count, 2)
        self.assertEqual(len(self.collections), 2)
        self.assertTrue(all(item.block_id is None for item in self.collections))
        self.assertEqual(
            [
                call.kwargs["quantity_delta"]
                for call in self.inventory_service.append_movement.await_args_list
            ],
            [Decimal("60.000"), Decimal("5.000")],
        )
        self.assertEqual(
            [
                call.kwargs["unit_cost"]
                for call in self.inventory_service.append_movement.await_args_list
            ],
            [Decimal("20"), Decimal("10")],
        )

    async def test_existing_setup_cannot_be_recorded_again(self):
        self.setup_repository.get_for_species = AsyncMock(
            return_value=SimpleNamespace(setup_date=date(2026, 10, 1))
        )
        request = self.request(
            "chickens",
            chicken_batches=[
                {
                    "name": "Opening layers",
                    "chicken_type": "layers",
                    "allocations": [
                        {"block_id": str(self.block_id), "quantity": 1}
                    ],
                }
            ],
        )

        with self.assertRaises(ConflictError):
            await self.service.create(self.farm, request)

        self.batch_repository.create.assert_not_awaited()
