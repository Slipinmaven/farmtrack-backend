import unittest
from datetime import date, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

from pydantic import ValidationError

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.schemas.chicken_loss import ChickenLossCreateRequest
from app.schemas.enums import (
    ActivityEntityType,
    ActivityType,
    ChickenBatchStatus,
    ChickenLossReason,
    ChickenType,
)
from app.services.chicken_loss_service import ChickenLossService


class FakeUnitOfWork:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False

    async def commit(self):
        pass


class FakeBatchRepository:
    def __init__(self, batches):
        self.batches = batches

    async def get_by_id(self, farm_id, batch_id):
        batch = self.batches.get(batch_id)
        if batch is None or batch.farm_id != farm_id:
            return None
        return batch


class FakeBatchBlockRepository:
    def __init__(self, inventory):
        self.inventory = inventory
        self.updated = []

    async def get_by_batch_and_block(self, batch_id, block_id):
        return self.inventory.get((batch_id, block_id))

    async def update(self, row):
        self.updated.append((row.batch_id, row.block_id, row.quantity))
        return row


class FakeLossRepository:
    def __init__(self):
        self.losses = []

    async def create_many(self, farm_id, records):
        losses = [
            SimpleNamespace(
                id=uuid4(),
                farm_id=farm_id,
                created_at=datetime.now(),
                updated_at=datetime.now(),
                **record,
            )
            for record in records
        ]
        self.losses.extend(losses)
        return losses

    async def list_by_farm(self, farm_id, **filters):
        return [loss for loss in self.losses if loss.farm_id == farm_id]


class FakeActivityService:
    def __init__(self):
        self.events = []

    async def record(self, **event):
        self.events.append(event)


class ChickenLossServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.farm_id = uuid4()
        self.farm = SimpleNamespace(id=self.farm_id, owner_id=uuid4())
        self.layers_batch_id = uuid4()
        self.broiler_batch_id = uuid4()
        self.block_ids = [uuid4() for _ in range(3)]
        self.batches = {
            self.layers_batch_id: SimpleNamespace(
                id=self.layers_batch_id,
                name="Layers A",
                farm_id=self.farm_id,
                status=ChickenBatchStatus.ACTIVE,
                chicken_type=ChickenType.LAYERS,
            ),
            self.broiler_batch_id: SimpleNamespace(
                id=self.broiler_batch_id,
                name="Broilers B",
                farm_id=self.farm_id,
                status=ChickenBatchStatus.ACTIVE,
                chicken_type=ChickenType.BROILER,
            ),
        }
        self.inventory = {
            (self.layers_batch_id, self.block_ids[0]): SimpleNamespace(
                batch_id=self.layers_batch_id,
                block_id=self.block_ids[0],
                quantity=100,
            ),
            (self.layers_batch_id, self.block_ids[1]): SimpleNamespace(
                batch_id=self.layers_batch_id,
                block_id=self.block_ids[1],
                quantity=40,
            ),
            (self.broiler_batch_id, self.block_ids[2]): SimpleNamespace(
                batch_id=self.broiler_batch_id,
                block_id=self.block_ids[2],
                quantity=60,
            ),
        }
        self.loss_repository = FakeLossRepository()
        self.batch_block_repository = FakeBatchBlockRepository(self.inventory)
        self.activity_service = FakeActivityService()
        self.service = ChickenLossService(
            loss_repository=cast(Any, self.loss_repository),
            chicken_batch_repository=cast(Any, FakeBatchRepository(self.batches)),
            batch_block_repository=cast(Any, self.batch_block_repository),
            unit_of_work=cast(Any, FakeUnitOfWork()),
            activity_service=cast(Any, self.activity_service),
        )

    def _request(self, items):
        return cast(Any, ChickenLossCreateRequest).model_validate(
            {
                "loss_date": date(2026, 10, 9),
                "items": items,
            }
        )

    async def test_multi_batch_multi_block_loss_updates_inventory_and_records_activity(self):
        request = self._request(
            [
                {
                    "batch_id": str(self.layers_batch_id),
                    "block_id": str(self.block_ids[0]),
                    "quantity": 3,
                    "reason": ChickenLossReason.DISEASE.value,
                    "notes": "Respiratory symptoms",
                },
                {
                    "batch_id": str(self.layers_batch_id),
                    "block_id": str(self.block_ids[1]),
                    "quantity": 2,
                    "reason": ChickenLossReason.NATURAL_DEATH.value,
                },
                {
                    "batch_id": str(self.broiler_batch_id),
                    "block_id": str(self.block_ids[2]),
                    "quantity": 4,
                    "reason": ChickenLossReason.PREDATOR.value,
                },
            ]
        )

        result = await self.service.create_losses(self.farm, request)

        self.assertEqual(len(result), 3)
        self.assertEqual(self.inventory[(self.layers_batch_id, self.block_ids[0])].quantity, 97)
        self.assertEqual(self.inventory[(self.layers_batch_id, self.block_ids[1])].quantity, 38)
        self.assertEqual(self.inventory[(self.broiler_batch_id, self.block_ids[2])].quantity, 56)
        self.assertEqual(sum(loss.quantity for loss in result), 9)
        self.assertEqual(len(self.loss_repository.losses), 3)
        self.assertEqual(len(self.activity_service.events), 1)
        event = self.activity_service.events[0]
        self.assertEqual(event["activity_type"], ActivityType.CHICKEN_LOSS_RECORDED)
        self.assertEqual(event["entity_type"], ActivityEntityType.CHICKEN_LOSS)
        self.assertEqual(event["details"]["total_quantity"], 9)
        self.assertEqual(len(event["details"]["loss_ids"]), 3)

    async def test_one_insufficient_line_rejects_entire_transaction(self):
        request = self._request(
            [
                {
                    "batch_id": str(self.layers_batch_id),
                    "block_id": str(self.block_ids[0]),
                    "quantity": 5,
                    "reason": ChickenLossReason.DISEASE.value,
                },
                {
                    "batch_id": str(self.broiler_batch_id),
                    "block_id": str(self.block_ids[2]),
                    "quantity": 61,
                    "reason": ChickenLossReason.PREDATOR.value,
                },
            ]
        )

        with self.assertRaises(ConflictError):
            await self.service.create_losses(self.farm, request)

        self.assertEqual(self.inventory[(self.layers_batch_id, self.block_ids[0])].quantity, 100)
        self.assertEqual(self.inventory[(self.broiler_batch_id, self.block_ids[2])].quantity, 60)
        self.assertEqual(self.loss_repository.losses, [])
        self.assertEqual(self.batch_block_repository.updated, [])
        self.assertEqual(self.activity_service.events, [])

    async def test_duplicate_pair_lines_are_aggregated_before_stock_check(self):
        request = self._request(
            [
                {
                    "batch_id": str(self.layers_batch_id),
                    "block_id": str(self.block_ids[0]),
                    "quantity": 60,
                    "reason": ChickenLossReason.DISEASE.value,
                },
                {
                    "batch_id": str(self.layers_batch_id),
                    "block_id": str(self.block_ids[0]),
                    "quantity": 50,
                    "reason": ChickenLossReason.INJURY.value,
                },
            ]
        )

        with self.assertRaises(ConflictError):
            await self.service.create_losses(self.farm, request)

        self.assertEqual(self.inventory[(self.layers_batch_id, self.block_ids[0])].quantity, 100)
        self.assertEqual(self.loss_repository.losses, [])

    async def test_opening_batch_loss_does_not_require_purchase_product_link(self):
        self.batches[self.layers_batch_id].is_opening_stock = True
        inventory_service = SimpleNamespace(append_movement=AsyncMock())
        service = ChickenLossService(
            loss_repository=cast(Any, self.loss_repository),
            chicken_batch_repository=cast(Any, FakeBatchRepository(self.batches)),
            batch_block_repository=cast(Any, self.batch_block_repository),
            unit_of_work=cast(Any, FakeUnitOfWork()),
            activity_service=cast(Any, self.activity_service),
            chicken_transaction_item_repository=cast(
                Any,
                SimpleNamespace(list_by_batch=AsyncMock(return_value=[])),
            ),
            inventory_service=cast(Any, inventory_service),
        )
        request = self._request(
            [
                {
                    "batch_id": str(self.layers_batch_id),
                    "block_id": str(self.block_ids[0]),
                    "quantity": 1,
                    "reason": ChickenLossReason.NATURAL_DEATH.value,
                }
            ]
        )

        result = await service.create_losses(self.farm, request)

        self.assertEqual(result[0].quantity, 1)
        inventory_service.append_movement.assert_not_awaited()

    async def test_missing_batch_and_inactive_batch_are_rejected(self):
        unknown_batch_id = uuid4()
        request = self._request(
            [
                {
                    "batch_id": str(unknown_batch_id),
                    "block_id": str(self.block_ids[0]),
                    "quantity": 1,
                    "reason": ChickenLossReason.OTHER.value,
                }
            ]
        )
        with self.assertRaises(ResourceNotFoundError):
            await self.service.create_losses(self.farm, request)

        self.batches[self.layers_batch_id].status = ChickenBatchStatus.COMPLETED
        inactive_batch_request = self._request(
            [
                {
                    "batch_id": str(self.layers_batch_id),
                    "block_id": str(self.block_ids[0]),
                    "quantity": 1,
                    "reason": ChickenLossReason.OTHER.value,
                }
            ]
        )
        with self.assertRaises(ConflictError):
            await self.service.create_losses(self.farm, inactive_batch_request)

    async def test_schema_rejects_empty_request_and_zero_quantity(self):
        with self.assertRaises(ValidationError):
            ChickenLossCreateRequest.model_validate(
                {"loss_date": date(2026, 10, 9), "items": []}
            )

        with self.assertRaises(ValidationError):
            ChickenLossCreateRequest.model_validate(
                {
                    "loss_date": date(2026, 10, 9),
                    "items": [
                        {
                            "batch_id": str(self.layers_batch_id),
                            "block_id": str(self.block_ids[0]),
                            "quantity": 0,
                            "reason": ChickenLossReason.DISEASE.value,
                        }
                    ],
                }
            )


if __name__ == "__main__":
    unittest.main()
