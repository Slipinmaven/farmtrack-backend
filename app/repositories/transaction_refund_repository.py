from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction_refunds import TransactionRefund


class TransactionRefundRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_transaction(
        self,
        transaction_id: UUID,
    ) -> list[TransactionRefund]:
        result = await self.session.execute(
            select(TransactionRefund)
            .where(TransactionRefund.transaction_id == transaction_id)
            .order_by(
                TransactionRefund.refund_date,
                TransactionRefund.refund_time,
                TransactionRefund.id,
            )
        )
        return list(result.scalars().all())

    async def get_total_by_transaction(self, transaction_id: UUID) -> Decimal:
        result = await self.session.execute(
            select(
                func.coalesce(func.sum(TransactionRefund.amount), 0)
            ).where(TransactionRefund.transaction_id == transaction_id)
        )
        return Decimal(result.scalar_one())

    async def create(self, data: dict) -> TransactionRefund:
        refund = TransactionRefund(**data)
        self.session.add(refund)
        await self.session.flush()
        return refund