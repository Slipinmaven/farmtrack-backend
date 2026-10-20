from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction_payments import TransactionPayment


class TransactionPaymentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_transaction(self, transaction_id: UUID) -> list[TransactionPayment]:
        result = await self.session.execute(
            select(TransactionPayment)
            .where(TransactionPayment.transaction_id == transaction_id)
            .order_by(
                TransactionPayment.payment_date,
                TransactionPayment.payment_time,
                TransactionPayment.id,
            )
        )
        return list(result.scalars().all())

    async def get_by_id(self, payment_id: UUID) -> TransactionPayment | None:
        result = await self.session.execute(
            select(TransactionPayment).where(TransactionPayment.id == payment_id)
        )
        return result.scalar_one_or_none()

    async def create(self, payment_data: dict) -> TransactionPayment:
        payment = TransactionPayment(**payment_data)
        self.session.add(payment)
        await self.session.flush()
        return payment

    async def update(self, payment: TransactionPayment) -> TransactionPayment:
        await self.session.flush()
        await self.session.refresh(payment)
        return payment

    async def delete(self, payment: TransactionPayment) -> None:
        await self.session.delete(payment)
        await self.session.flush()