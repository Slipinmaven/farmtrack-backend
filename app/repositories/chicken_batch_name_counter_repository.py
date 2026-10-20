from datetime import date
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chicken_batch_name_counter import ChickenBatchNameCounter


class ChickenBatchNameCounterRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def allocate_next_number(self, farm_id: UUID, batch_date: date) -> int:
        statement = insert(ChickenBatchNameCounter).values(
            farm_id=farm_id,
            batch_date=batch_date,
            last_number=1,
        )
        statement = statement.on_conflict_do_update(
            constraint="uq_chicken_batch_name_counters_farm_date",
            set_={
                "last_number": ChickenBatchNameCounter.last_number + 1,
            },
        ).returning(ChickenBatchNameCounter.last_number)
        result = await self.session.execute(statement)
        return result.scalar_one()