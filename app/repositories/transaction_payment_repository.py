from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError
from app.models.transaction_payments import TransactionPayment


_MPESA_REFERENCE_INDEX = "uq_transaction_payments_mpesa_reference"


def _is_duplicate_mpesa_reference(error: IntegrityError) -> bool:
    original_error = error.orig
    while original_error is not None:
        diagnostic = getattr(original_error, "diag", None)
        if getattr(diagnostic, "constraint_name", None) == _MPESA_REFERENCE_INDEX:
            return True
        if _MPESA_REFERENCE_INDEX in str(original_error):
            return True
        original_error = original_error.__cause__ or original_error.__context__
    return False


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
        try:
            await self.session.flush()
        except IntegrityError as error:
            if _is_duplicate_mpesa_reference(error):
                raise ConflictError(
                    "This M-Pesa transaction reference has already been recorded."
                ) from error
            raise
        return payment

    async def update(self, payment: TransactionPayment) -> TransactionPayment:
        await self.session.flush()
        await self.session.refresh(payment)
        return payment

    async def delete(self, payment: TransactionPayment) -> None:
        await self.session.delete(payment)
        await self.session.flush()