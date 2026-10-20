import unittest
from datetime import date, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

from pydantic import ValidationError

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.schemas.chicken_movement import (
    ChickenMovementBatchCreateRequest,
    ChickenMovementCreateRequest,
)
from app.schemas.enums import ActivityEntityType, ActivityType, ChickenBatchStatus, ChickenType
from app.services.chicken_movement_service import ChickenMovementService


class FakeUnitOfWork:
    def __init__(self):
        self.commit_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False

    async def commit(self):
        self.commit_count += 1


class FakeBatchRepository:
    def __init__(self, batches):
        self.batches = batches

    async def get_by_id(self, farm_id, batch_id):
        batch = self.batches.get(batch_id)
        return batch if batch is not None and batch.farm_id == farm_id else None


class FakeBlockRepository:
    def __init__(self, blocks):
        self.blocks = blocks
        self.lock_order = []

    async def get_by_id_for_update(self, farm_id, block_id):
        self.lock_order.append(block_id)
        block = self.blocks.get(block_id)
        if block is None or block.farm_id != farm_id:
            return None
        return block


class FakeBatchBlockRepository:
    def __init__(self, inventory):
        self.inventory = inventory

    async def get_by_batch_and_block(self, batch_id, block_id):
        return self.inventory.get((batch_id, block_id))

    async def get_total_quantity_by_block(self, block_id):
        return sum(
            row.quantity
            for (_, candidate_block_id), row in self.inventory.items()
            if candidate_block_id == block_id
        )

    async def update(self, row):
        return row

    async def create(self, data):
        row = SimpleNamespace(**data)
        self.inventory[(row.batch_id, row.block_id)] = row
        return row


class FakeMovementRepository:
    def __init__(self):
        self.movements = []
        self.history_result = ([], 0)
        self.history_call = None

    async def create(self, farm_id, data):
        movement = SimpleNamespace(
            id=uuid4(),
            farm_id=farm_id,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            **data,
        )
        self.movements.append(movement)
        return movement

    async def list_by_farm(self, farm_id, **filters):
        return [movement for movement in self.movements if movement.farm_id == farm_id]

    async def list_block_history(self, farm_id, block_id, **filters):
        self.history_call = (farm_id, block_id, filters)
        return self.history_result


class FakeActivityService:
    def __init__(self):
        self.events = []

    async def record(self, **event):
        self.events.append(event)


class ChickenMovementServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.farm_id = uuid4()
        self.farm = SimpleNamespace(id=self.farm_id, owner_id=uuid4())
        self.batch_id = uuid4()
        self.source_block_id = uuid4()
        self.target_block_id = uuid4()
        self.batch = SimpleNamespace(
            id=self.batch_id,
            farm_id=self.farm_id,
            name="Batch A",
            status=ChickenBatchStatus.ACTIVE,
            chicken_type=ChickenType.LAYERS,
        )
        self.second_batch_id = uuid4()
        self.second_batch = SimpleNamespace(
            id=self.second_batch_id,
            farm_id=self.farm_id,
            name="Batch B",
            status=ChickenBatchStatus.ACTIVE,
            chicken_type=ChickenType.LAYERS,
        )
        self.source_block = SimpleNamespace(
            id=self.source_block_id,
            farm_id=self.farm_id,
            name="Source",
            is_active=True,
            capacity=100,
            over_capacity_limit=10,
        )
        self.target_block = SimpleNamespace(
            id=self.target_block_id,
            farm_id=self.farm_id,
            name="Target",
            is_active=True,
            capacity=100,
            over_capacity_limit=10,
        )
        self.source_row = SimpleNamespace(
            batch_id=self.batch_id,
            block_id=self.source_block_id,
            quantity=25,
        )
        self.second_source_row = SimpleNamespace(
            batch_id=self.second_batch_id,
            block_id=self.source_block_id,
            quantity=12,
        )
        self.other_target_row = SimpleNamespace(
            batch_id=uuid4(),
            block_id=self.target_block_id,
            quantity=20,
        )
        self.inventory = {
            (self.batch_id, self.source_block_id): self.source_row,
            (self.second_batch_id, self.source_block_id): self.second_source_row,
            (self.other_target_row.batch_id, self.target_block_id): self.other_target_row,
        }
        self.block_repository = FakeBlockRepository(
            {
                self.source_block_id: self.source_block,
                self.target_block_id: self.target_block,
            }
        )
        self.batch_block_repository = FakeBatchBlockRepository(self.inventory)
        self.batch_repository = FakeBatchRepository(
            {
                self.batch_id: self.batch,
                self.second_batch_id: self.second_batch,
            }
        )
        self.movement_repository = FakeMovementRepository()
        self.activity_service = FakeActivityService()
        self.unit_of_work = FakeUnitOfWork()
        self.service = ChickenMovementService(
            movement_repository=cast(Any, self.movement_repository),
            chicken_batch_repository=cast(Any, self.batch_repository),
            block_repository=cast(Any, self.block_repository),
            batch_block_repository=cast(Any, self.batch_block_repository),
            unit_of_work=cast(Any, self.unit_of_work),
            activity_service=cast(Any, self.activity_service),
        )

    def _request(self, quantity):
        return cast(Any, ChickenMovementCreateRequest).model_validate(
            {
                "batch_id": str(self.batch_id),
                "from_block_id": str(self.source_block_id),
                "to_block_id": str(self.target_block_id),
                "quantity": quantity,
                "movement_date": date(2026, 10, 9),
                "reason": "Sick chickens isolation",
            }
        )

    def _batch_request(self, quantities):
        return cast(Any, ChickenMovementBatchCreateRequest).model_validate(
            {
                "from_block_id": str(self.source_block_id),
                "to_block_id": str(self.target_block_id),
                "movement_date": date(2026, 10, 9),
                "items": [
                    {"batch_id": str(batch_id), "quantity": quantity}
                    for batch_id, quantity in quantities
                ],
            }
        )

    async def test_batch_movement_moves_multiple_batches_atomically(self):
        response = await self.service.create_batch_movement(
            self.farm,
            self._batch_request(
                [(self.batch_id, 10), (self.second_batch_id, 5)]
            ),
        )

        self.assertEqual(len(response), 2)
        self.assertEqual(self.source_row.quantity, 15)
        self.assertEqual(self.second_source_row.quantity, 7)
        self.assertEqual(
            self.inventory[(self.batch_id, self.target_block_id)].quantity,
            10,
        )
        self.assertEqual(
            self.inventory[(self.second_batch_id, self.target_block_id)].quantity,
            5,
        )
        self.assertEqual(len(self.movement_repository.movements), 2)
        self.assertEqual(len(self.activity_service.events), 2)
        self.assertEqual(self.unit_of_work.commit_count, 1)

    async def test_batch_movement_capacity_failure_changes_no_batch_inventory(self):
        self.target_block.capacity = 22
        self.target_block.over_capacity_limit = 3

        with self.assertRaises(ConflictError):
            await self.service.create_batch_movement(
                self.farm,
                self._batch_request(
                    [(self.batch_id, 5), (self.second_batch_id, 4)]
                ),
            )

        self.assertEqual(self.source_row.quantity, 25)
        self.assertEqual(self.second_source_row.quantity, 12)
        self.assertNotIn((self.batch_id, self.target_block_id), self.inventory)
        self.assertNotIn(
            (self.second_batch_id, self.target_block_id),
            self.inventory,
        )
        self.assertEqual(self.movement_repository.movements, [])
        self.assertEqual(self.activity_service.events, [])
        self.assertEqual(self.unit_of_work.commit_count, 0)

    async def test_batch_movement_insufficient_stock_changes_nothing(self):
        with self.assertRaises(ConflictError):
            await self.service.create_batch_movement(
                self.farm,
                self._batch_request(
                    [(self.batch_id, 10), (self.second_batch_id, 13)]
                ),
            )

        self.assertEqual(self.source_row.quantity, 25)
        self.assertEqual(self.second_source_row.quantity, 12)
        self.assertNotIn((self.batch_id, self.target_block_id), self.inventory)
        self.assertNotIn(
            (self.second_batch_id, self.target_block_id),
            self.inventory,
        )
        self.assertEqual(self.movement_repository.movements, [])
        self.assertEqual(self.activity_service.events, [])
        self.assertEqual(self.unit_of_work.commit_count, 0)

    def test_batch_request_rejects_duplicate_batches(self):
        with self.assertRaises(ValidationError):
            self._batch_request(
                [(self.batch_id, 2), (self.batch_id, 3)]
            )

    def test_batch_request_rejects_same_source_and_destination(self):
        with self.assertRaises(ValidationError):
            ChickenMovementBatchCreateRequest.model_validate(
                {
                    "from_block_id": str(self.source_block_id),
                    "to_block_id": str(self.source_block_id),
                    "movement_date": date(2026, 10, 9),
                    "items": [
                        {"batch_id": str(self.batch_id), "quantity": 1},
                    ],
                }
            )

    async def test_block_history_returns_paged_named_movement_records(self):
        movement = SimpleNamespace(
            id=uuid4(),
            batch_id=self.batch_id,
            from_block_id=self.source_block_id,
            to_block_id=self.target_block_id,
            quantity=7,
            movement_date=date(2026, 10, 9),
            reason="Age separation",
            notes="Moved before vaccination",
        )
        self.movement_repository.history_result = (
            [(movement, "Batch A", "Source", "Target")],
            26,
        )

        response = await self.service.list_block_history(
            self.farm,
            self.source_block_id,
            direction="outgoing",
            search="  Batch A ",
            from_date=date(2026, 10, 1),
            offset=20,
            limit=10,
        )

        self.assertEqual(response.total_count, 26)
        self.assertEqual(response.offset, 20)
        self.assertEqual(response.limit, 10)
        self.assertEqual(response.items[0].batch_name, "Batch A")
        self.assertEqual(response.items[0].from_block_name, "Source")
        self.assertEqual(response.items[0].to_block_name, "Target")
        self.assertEqual(response.items[0].quantity, 7)
        self.assertEqual(
            self.movement_repository.history_call,
            (
                self.farm_id,
                self.source_block_id,
                {
                    "direction": "outgoing",
                    "search": "Batch A",
                    "from_date": date(2026, 10, 1),
                    "to_date": None,
                    "offset": 20,
                    "limit": 10,
                },
            ),
        )

    async def test_block_history_rejects_inverted_date_range(self):
        with self.assertRaises(ConflictError):
            await self.service.list_block_history(
                self.farm,
                self.source_block_id,
                from_date=date(2026, 10, 10),
                to_date=date(2026, 10, 1),
            )

    async def test_movement_updates_both_inventory_rows_and_records_audit(self):
        response = await self.service.create_movement(self.farm, self._request(10))

        self.assertEqual(self.source_row.quantity, 15)
        self.assertEqual(
            self.inventory[(self.batch_id, self.target_block_id)].quantity,
            10,
        )
        self.assertEqual(response.quantity, 10)
        self.assertEqual(response.from_block_id, self.source_block_id)
        self.assertEqual(response.to_block_id, self.target_block_id)
        self.assertEqual(len(self.movement_repository.movements), 1)
        self.assertEqual(
            self.activity_service.events[-1]["activity_type"],
            ActivityType.CHICKEN_MOVEMENT_CREATED,
        )
        self.assertEqual(
            self.activity_service.events[-1]["entity_type"],
            ActivityEntityType.CHICKEN_MOVEMENT,
        )
        self.assertEqual(
            self.block_repository.lock_order,
            sorted(
                [self.source_block_id, self.target_block_id],
                key=str,
            ),
        )

    async def test_insufficient_source_stock_does_not_mutate_inventory(self):
        with self.assertRaises(ConflictError):
            await self.service.create_movement(self.farm, self._request(26))

        self.assertEqual(self.source_row.quantity, 25)
        self.assertNotIn((self.batch_id, self.target_block_id), self.inventory)
        self.assertEqual(self.movement_repository.movements, [])

    async def test_destination_capacity_includes_over_capacity_limit(self):
        self.target_block.capacity = 22
        self.target_block.over_capacity_limit = 3

        await self.service.create_movement(self.farm, self._request(5))
        self.assertEqual(self.inventory[(self.batch_id, self.target_block_id)].quantity, 5)

        self.source_row.quantity = 25
        with self.assertRaises(ConflictError):
            await self.service.create_movement(self.farm, self._request(1))
        self.assertEqual(self.source_row.quantity, 25)
        self.assertEqual(self.inventory[(self.batch_id, self.target_block_id)].quantity, 5)
        self.assertEqual(len(self.movement_repository.movements), 1)

    async def test_rejects_inactive_batch_and_inactive_block(self):
        self.batch.status = ChickenBatchStatus.COMPLETED
        with self.assertRaises(ConflictError):
            await self.service.create_movement(self.farm, self._request(1))

        self.batch.status = ChickenBatchStatus.ACTIVE
        self.target_block.is_active = False
        with self.assertRaises(ConflictError):
            await self.service.create_movement(self.farm, self._request(1))

        self.assertEqual(self.source_row.quantity, 25)
        self.assertEqual(self.movement_repository.movements, [])

    async def test_schema_rejects_same_block_and_nonpositive_quantity(self):
        data = {
            "batch_id": str(self.batch_id),
            "from_block_id": str(self.source_block_id),
            "to_block_id": str(self.source_block_id),
            "quantity": 1,
            "movement_date": date(2026, 10, 9),
        }
        with self.assertRaises(ValidationError):
            ChickenMovementCreateRequest.model_validate(data)

        data["to_block_id"] = str(self.target_block_id)
        data["quantity"] = 0
        with self.assertRaises(ValidationError):
            ChickenMovementCreateRequest.model_validate(data)


if __name__ == "__main__":
    unittest.main()
