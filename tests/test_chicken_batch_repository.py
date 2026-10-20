from decimal import Decimal
from uuid import uuid4

import pytest

from app.repositories.chicken_batch_repository import ChickenBatchRepository


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.executed = False

    async def execute(self, _query):
        self.executed = True
        return FakeResult(self.rows)


@pytest.mark.asyncio
async def test_purchase_unit_cost_is_weighted_by_base_quantity():
    batch_id = uuid4()
    session = FakeSession(
        [
            (batch_id, Decimal("100.00"), Decimal("10"), Decimal("1")),
            (batch_id, Decimal("90.00"), Decimal("5"), Decimal("1")),
        ]
    )
    repository = ChickenBatchRepository(session=session)

    costs = await repository.get_estimated_purchase_unit_costs(
        uuid4(),
        {batch_id},
    )

    assert costs[batch_id] == Decimal("12.6667")


@pytest.mark.asyncio
async def test_purchase_unit_cost_uses_conversion_factor():
    batch_id = uuid4()
    session = FakeSession(
        [(batch_id, Decimal("60.00"), Decimal("2"), Decimal("3"))]
    )
    repository = ChickenBatchRepository(session=session)

    costs = await repository.get_estimated_purchase_unit_costs(
        uuid4(),
        {batch_id},
    )

    assert costs[batch_id] == Decimal("10.00")


@pytest.mark.asyncio
async def test_purchase_unit_cost_skips_query_for_no_batches():
    session = FakeSession([])
    repository = ChickenBatchRepository(session=session)

    costs = await repository.get_estimated_purchase_unit_costs(uuid4(), set())

    assert costs == {}
    assert not session.executed
