from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy.dialects import sqlite

from app.repositories.chicken_movement_repository import ChickenMovementRepository


class FakeResult:
    def __init__(self, rows=None, total=0):
        self.rows = rows or []
        self.total = total

    def tuples(self):
        return self

    def all(self):
        return self.rows

    def scalar_one(self):
        return self.total


class FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    async def execute(self, query):
        self.queries.append(query)
        if len(self.queries) == 1:
            return FakeResult(rows=self.rows)
        return FakeResult(total=31)


@pytest.mark.asyncio
async def test_block_history_filters_search_and_paginates():
    farm_id = uuid4()
    block_id = uuid4()
    movement_row = object()
    session = FakeSession([(movement_row, "Batch 12", "North", "South")])
    repository = ChickenMovementRepository(session=session)

    rows, total = await repository.list_block_history(
        farm_id,
        block_id,
        direction="incoming",
        search="Batch 12",
        from_date=date(2026, 9, 1),
        offset=20,
        limit=10,
    )

    assert rows == [(movement_row, "Batch 12", "North", "South")]
    assert total == 31
    assert len(session.queries) == 2

    page_query = session.queries[0]
    sql = str(page_query.compile(dialect=sqlite.dialect()))
    params = page_query.compile(dialect=sqlite.dialect()).params
    assert "chicken_movements.to_block_id" in sql
    assert "chicken_movements.movement_date >=" in sql
    assert "LIMIT" in sql
    assert "OFFSET" in sql
    assert "%Batch 12%" in params.values()
    assert date(2026, 9, 1) in params.values()

    count_sql = str(session.queries[1].compile(dialect=sqlite.dialect()))
    assert "count(chicken_movements.id)" in count_sql.lower()
    assert "LIMIT" not in count_sql

