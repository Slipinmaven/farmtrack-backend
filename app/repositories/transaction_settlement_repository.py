from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction_settlements import TransactionSettlement


class TransactionSettlementRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_transaction(
        self,
        transaction_id: UUID,
    ) -> list[TransactionSettlement]:
        result = await self.session.execute(
            select(TransactionSettlement)
            .where(TransactionSettlement.transaction_id == transaction_id)
            .order_by(
                TransactionSettlement.settlement_date,
                TransactionSettlement.created_at,
                TransactionSettlement.id,
            )
        )
        return list(result.scalars().all())

    async def get_total_by_transaction(self, transaction_id: UUID) -> Decimal:
        result = await self.session.execute(
            select(
                func.coalesce(func.sum(TransactionSettlement.total_value), 0)
            ).where(TransactionSettlement.transaction_id == transaction_id)
        )
        return Decimal(result.scalar_one())

    async def create(self, data: dict) -> TransactionSettlement:
        settlement = TransactionSettlement(**data)
        self.session.add(settlement)
        await self.session.flush()
        return settlement
