from datetime import date
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction_reference_counter import TransactionReferenceCounter


class TransactionReferenceCounterRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def allocate_next_number(
        self,
        farm_id: UUID,
        reference_type: str,
        reference_date: date,
    ) -> int:
        statement = insert(TransactionReferenceCounter).values(
            farm_id=farm_id,
            reference_type=reference_type,
            reference_date=reference_date,
            last_number=1,
        )
        statement = statement.on_conflict_do_update(
            constraint="uq_transaction_reference_counters_scope",
            set_={
                "last_number": TransactionReferenceCounter.last_number + 1,
            },
        ).returning(TransactionReferenceCounter.last_number)
        result = await self.session.execute(statement)
        return result.scalar_one()