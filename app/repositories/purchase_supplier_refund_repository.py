from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.purchase_supplier_refunds import PurchaseSupplierRefund


class PurchaseSupplierRefundRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_transaction(
        self,
        transaction_id: UUID,
    ) -> list[PurchaseSupplierRefund]:
        result = await self.session.execute(
            select(PurchaseSupplierRefund)
            .where(PurchaseSupplierRefund.transaction_id == transaction_id)
            .order_by(
                PurchaseSupplierRefund.refund_date,
                PurchaseSupplierRefund.refund_time,
                PurchaseSupplierRefund.id,
            )
        )
        return list(result.scalars().all())

    async def get_total_by_transaction(self, transaction_id: UUID) -> Decimal:
        result = await self.session.execute(
            select(func.coalesce(func.sum(PurchaseSupplierRefund.amount), 0)).where(
                PurchaseSupplierRefund.transaction_id == transaction_id
            )
        )
        return Decimal(result.scalar_one())

    async def get_total_by_return_item(self, return_item_id: UUID) -> Decimal:
        result = await self.session.execute(
            select(func.coalesce(func.sum(PurchaseSupplierRefund.amount), 0)).where(
                PurchaseSupplierRefund.purchase_return_item_id == return_item_id
            )
        )
        return Decimal(result.scalar_one())

    async def create(self, data: dict) -> PurchaseSupplierRefund:
        refund = PurchaseSupplierRefund(**data)
        self.session.add(refund)
        await self.session.flush()
        return refund