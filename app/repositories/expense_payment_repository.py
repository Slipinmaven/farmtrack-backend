from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.expense_payment import ExpensePayment


class ExpensePaymentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, expense_id: UUID, data: dict) -> ExpensePayment:
        payment = ExpensePayment(expense_id=expense_id, **data)
        self.session.add(payment)
        await self.session.flush()
        return payment

    async def list_by_expense(self, expense_id: UUID) -> list[ExpensePayment]:
        result = await self.session.execute(
            select(ExpensePayment)
            .where(ExpensePayment.expense_id == expense_id)
            .order_by(
                ExpensePayment.payment_date,
                ExpensePayment.created_at,
                ExpensePayment.id,
            )
        )
        return list(result.scalars().all())
