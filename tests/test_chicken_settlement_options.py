import unittest
from datetime import date
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

from app.core.unit_of_work import UnitOfWork
from app.models.farm import Farm
from app.repositories.batch_block_repository import BatchBlockRepository
from app.repositories.block_repository import BlockRepository
from app.repositories.chicken_batch_repository import ChickenBatchRepository
from app.repositories.product_repository import ProductRepository
from app.schemas.enums import ChickenBatchStatus, ChickenType
from app.services.chicken_sale_options_service import ChickenSaleOptionsService


class FakeUnitOfWork:
    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc_value, _traceback):
        return False


class ChickenSettlementOptionsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.farm = Farm(id=uuid4(), owner_id=uuid4(), name="Farm Track")
        self.batch_id = uuid4()
        self.batch = SimpleNamespace(
            id=self.batch_id,
            name="Layers 01",
            status=ChickenBatchStatus.ACTIVE,
            chicken_type=ChickenType.LAYERS,
            hatch_date=date(2026, 1, 1),
            batch_blocks=[],
        )
        self.batches_seen = {}
        self.blocks_seen = {}
        self.service = ChickenSaleOptionsService(
            product_repository=cast(ProductRepository, SimpleNamespace()),
            block_repository=cast(
                BlockRepository,
                SimpleNamespace(
                    list_by_farm=self.list_blocks,
                    list_active_with_batch_stock=self.list_issue_blocks,
                    list_active_with_chicken_stock=self.list_stocked_blocks,
                ),
            ),
            chicken_batch_repository=cast(
                ChickenBatchRepository,
                SimpleNamespace(
                    list_for_settlement=self.list_batches,
                    get_by_id=self.get_batch,
                ),
            ),
            batch_block_repository=cast(
                BatchBlockRepository,
                SimpleNamespace(
                    get_total_quantities_by_blocks=self.get_block_quantities,
                ),
            ),
            unit_of_work=cast(UnitOfWork, FakeUnitOfWork()),
        )

    async def list_batches(self, farm_id, **kwargs):
        self.batches_seen = {"farm_id": farm_id, **kwargs}
        return [
            (
                SimpleNamespace(
                    id=uuid4(),
                    name=f"Batch {index}",
                    chicken_type=ChickenType.LAYERS,
                    hatch_date=None,
                ),
                12,
            )
            for index in range(31)
        ]

    async def list_blocks(self, farm_id, **kwargs):
        self.blocks_seen = {"farm_id": farm_id, **kwargs}
        return [
            SimpleNamespace(
                id=uuid4(),
                name=f"Block {index}",
                capacity=100,
                over_capacity_limit=0,
            )
            for index in range(31)
        ]

    async def list_issue_blocks(self, farm_id, batch_id, **kwargs):
        self.blocks_seen = {
            "farm_id": farm_id,
            "batch_id": batch_id,
            **kwargs,
        }
        return []

    async def list_stocked_blocks(self, farm_id, **kwargs):
        self.blocks_seen = {"farm_id": farm_id, **kwargs}
        return [
            (
                SimpleNamespace(
                    id=uuid4(),
                    name=f"Stocked block {index}",
                    capacity=100,
                    over_capacity_limit=0,
                ),
                24,
            )
            for index in range(31)
        ]

    async def get_batch(self, farm_id, batch_id):
        return self.batch if farm_id == self.farm.id and batch_id == self.batch_id else None

    async def get_block_quantities(self, _block_ids):
        return {}

    async def test_batch_lookup_is_bounded_and_supports_paging(self):
        result = await self.service.get_settlement_options(
            self.farm,
            selection="receive_batch",
            search="layer",
            offset=30,
        )

        self.assertEqual(len(result.batches), 30)
        self.assertTrue(result.has_more)
        self.assertEqual(self.batches_seen["farm_id"], self.farm.id)
        self.assertEqual(self.batches_seen["search"], "layer")
        self.assertEqual(self.batches_seen["limit"], 31)
        self.assertEqual(self.batches_seen["offset"], 30)

    async def test_block_lookup_is_bounded_and_reports_remaining_results(self):
        result = await self.service.get_settlement_options(
            self.farm,
            selection="receive_block",
            search="north",
        )

        self.assertEqual(len(result.blocks), 30)
        self.assertTrue(result.has_more)
        self.assertEqual(self.blocks_seen["search"], "north")
        self.assertEqual(self.blocks_seen["limit"], 31)

    async def test_issue_block_lookup_requires_owned_active_batch(self):
        result = await self.service.get_settlement_options(
            self.farm,
            selection="issue_block",
            search="north",
            batch_id=self.batch_id,
        )

        self.assertEqual(result.blocks, [])
        self.assertEqual(self.blocks_seen["batch_id"], self.batch_id)
        self.assertEqual(self.blocks_seen["limit"], 31)

    async def test_issue_block_can_be_selected_before_batch(self):
        result = await self.service.get_settlement_options(
            self.farm,
            selection="issue_block",
            search="north",
        )

        self.assertEqual(len(result.blocks), 30)
        self.assertTrue(result.has_more)
        self.assertEqual(result.blocks[0].batch_quantity, 24)
        self.assertEqual(self.blocks_seen["search"], "north")
        self.assertEqual(self.blocks_seen["limit"], 31)

    async def test_issue_batches_are_filtered_by_selected_block(self):
        block_id = uuid4()
        await self.service.get_settlement_options(
            self.farm,
            selection="issue_batch",
            search=None,
            block_id=block_id,
        )

        self.assertEqual(self.batches_seen["block_id"], block_id)
        self.assertTrue(self.batches_seen["require_active_stock"])


if __name__ == "__main__":
    unittest.main()
