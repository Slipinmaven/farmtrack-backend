from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.sale_return_item_allocations import SaleReturnItemAllocation
from app.models.sale_return_items import SaleReturnItem
from app.models.sale_returns import SaleReturn


class SaleReturnRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    def _return_query(self):
        return select(SaleReturn).options(
            selectinload(SaleReturn.items).selectinload(
                SaleReturnItem.batch_allocations
            )
        )

    async def list_by_transaction(self, transaction_id: UUID) -> list[SaleReturn]:
        result = await self.session.execute(
            self._return_query()
            .where(SaleReturn.transaction_id == transaction_id)
            .order_by(
                SaleReturn.return_date,
                SaleReturn.return_time,
                SaleReturn.created_at,
                SaleReturn.id,
            )
        )
        return list(result.scalars().all())

    async def get_quantities_by_type(
        self,
        transaction_id: UUID,
        return_type: str,
    ) -> dict[UUID, Decimal]:
        result = await self.session.execute(
            select(SaleReturnItem.transaction_item_id, func.sum(SaleReturnItem.quantity))
            .join(SaleReturn, SaleReturn.id == SaleReturnItem.sale_return_id)
            .where(
                SaleReturn.transaction_id == transaction_id,
                SaleReturn.return_type == return_type,
            )
            .group_by(SaleReturnItem.transaction_item_id)
        )
        return {
            transaction_item_id: quantity
            for transaction_item_id, quantity in result.all()
        }

    async def get_credited_quantities_by_item(
        self,
        transaction_id: UUID,
    ) -> dict[UUID, Decimal]:
        result = await self.session.execute(
            select(SaleReturnItem.transaction_item_id, func.sum(SaleReturnItem.quantity))
            .join(SaleReturn, SaleReturn.id == SaleReturnItem.sale_return_id)
            .where(SaleReturn.transaction_id == transaction_id)
            .group_by(SaleReturnItem.transaction_item_id)
        )
        return {
            transaction_item_id: quantity
            for transaction_item_id, quantity in result.all()
        }

    async def get_credit_amounts_by_item(
        self,
        transaction_id: UUID,
    ) -> dict[UUID, Decimal]:
        result = await self.session.execute(
            select(
                SaleReturnItem.transaction_item_id,
                func.sum(SaleReturnItem.credit_amount),
            )
            .join(SaleReturn, SaleReturn.id == SaleReturnItem.sale_return_id)
            .where(SaleReturn.transaction_id == transaction_id)
            .group_by(SaleReturnItem.transaction_item_id)
        )
        return {
            transaction_item_id: amount
            for transaction_item_id, amount in result.all()
        }

    async def get_total_credit_by_transaction(self, transaction_id: UUID) -> Decimal:
        result = await self.session.execute(
            select(func.coalesce(func.sum(SaleReturnItem.credit_amount), 0))
            .join(SaleReturn, SaleReturn.id == SaleReturnItem.sale_return_id)
            .where(SaleReturn.transaction_id == transaction_id)
        )
        return Decimal(result.scalar_one())

    async def get_returned_quantities_by_batch(
        self,
        transaction_id: UUID,
    ) -> dict[tuple[UUID, UUID], int]:
        result = await self.session.execute(
            select(
                SaleReturnItem.transaction_item_id,
                SaleReturnItemAllocation.batch_id,
                func.sum(SaleReturnItemAllocation.quantity),
            )
            .join(SaleReturn, SaleReturn.id == SaleReturnItem.sale_return_id)
            .join(
                SaleReturnItemAllocation,
                SaleReturnItemAllocation.sale_return_item_id == SaleReturnItem.id,
            )
            .where(
                SaleReturn.transaction_id == transaction_id,
                SaleReturn.return_type == "delivered_return",
            )
            .group_by(
                SaleReturnItem.transaction_item_id,
                SaleReturnItemAllocation.batch_id,
            )
        )
        return {
            (transaction_item_id, batch_id): quantity
            for transaction_item_id, batch_id, quantity in result.all()
        }

    async def create_return(self, data: dict) -> SaleReturn:
        sale_return = SaleReturn(**data)
        self.session.add(sale_return)
        await self.session.flush()
        return sale_return

    async def create_item(self, data: dict) -> SaleReturnItem:
        item = SaleReturnItem(**data)
        self.session.add(item)
        await self.session.flush()
        return item

    async def create_allocation(self, data: dict) -> SaleReturnItemAllocation:
        allocation = SaleReturnItemAllocation(**data)
        self.session.add(allocation)
        await self.session.flush()
        return allocation