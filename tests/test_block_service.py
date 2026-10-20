from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.exceptions import ConflictError
from app.schemas.block import BlockUpdateRequest
from app.schemas.enums import ChickenBatchStatus, ChickenType
from app.services.block_service import BlockService


class FakeUnitOfWork:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return None

    async def commit(self):
        return None


class FakeBlockRepository:
    def __init__(self, block, occupied):
        self.block = block
        self.occupied = occupied
        self.deleted = False

    async def list_by_farm(
        self,
        farm_id,
        search=None,
        is_active=None,
        limit=None,
        offset=0,
    ):
        blocks = [self.block][offset:]
        return blocks if limit is None else blocks[:limit]

    async def get_by_id(self, farm_id, block_id):
        return self.block if block_id == self.block.id else None

    async def get_by_id_for_update(self, farm_id, block_id):
        return self.block if block_id == self.block.id else None

    async def get_occupancy_by_farm(self, farm_id):
        return {self.block.id: self.occupied} if self.occupied else {}

    async def get_occupied_chickens(self, farm_id, block_id):
        return self.occupied

    async def list_batch_occupancy(self, farm_id, block_id):
        return getattr(self, "batch_assignments", [])

    async def update(self, block):
        return block

    async def delete(self, block):
        self.deleted = True


class FakeActivityService:
    async def record(self, **kwargs):
        return None


def make_service(occupied):
    now = datetime.now(timezone.utc)
    farm_id = uuid4()
    block = SimpleNamespace(
        id=uuid4(),
        farm_id=farm_id,
        name="North house",
        description="Layers",
        capacity=20,
        over_capacity_limit=5,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    farm = SimpleNamespace(id=farm_id, owner_id=uuid4())
    repository = FakeBlockRepository(block, occupied)
    service = BlockService(
        block_repository=repository,
        activity_service=FakeActivityService(),
        unit_of_work=FakeUnitOfWork(),
    )
    return service, repository, farm, block


@pytest.mark.asyncio
async def test_list_blocks_includes_live_occupied_chicken_count():
    service, _, farm, block = make_service(occupied=17)

    response = await service.list_blocks(farm)

    assert response[0].id == block.id
    assert response[0].occupied_chickens == 17


@pytest.mark.asyncio
async def test_get_block_includes_batch_quantities_and_current_ages():
    service, repository, farm, block = make_service(occupied=12)
    repository.batch_assignments = [
        SimpleNamespace(
            batch=SimpleNamespace(
                id=uuid4(),
                name="Spring layers",
                chicken_type=ChickenType.LAYERS,
                breed="Rhode Island Red",
                status=ChickenBatchStatus.ACTIVE,
                hatch_date=date.today() - timedelta(days=400),
                notes="Keep separate",
            ),
            quantity=12,
        )
    ]

    response = await service.get_block(farm, block.id)

    assert response.occupied_chickens == 12
    assert len(response.batches) == 1
    assert response.batches[0].batch_name == "Spring layers"
    assert response.batches[0].quantity == 12
    assert response.batches[0].age_days == 400


@pytest.mark.asyncio
async def test_update_rejects_capacity_below_current_occupancy():
    service, _, farm, block = make_service(occupied=18)
    update = BlockUpdateRequest(capacity=10, over_capacity_limit=5)

    with pytest.raises(ConflictError, match="current occupancy of 18"):
        await service.update_block(farm, block.id, update)


@pytest.mark.asyncio
async def test_delete_rejects_block_with_assigned_chickens():
    service, repository, farm, block = make_service(occupied=2)

    with pytest.raises(ConflictError, match="Move or clear the 2 chickens"):
        await service.delete_block(farm, block.id)

    assert repository.deleted is False
