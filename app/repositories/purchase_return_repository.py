from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.purchase_return_item_allocations import PurchaseReturnItemAllocation
from app.models.purchase_return_items import PurchaseReturnItem
from app.models.purchase_returns import PurchaseReturn


class PurchaseReturnRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    def _return_query(self):
        return select(PurchaseReturn).options(
            selectinload(PurchaseReturn.items).selectinload(
                PurchaseReturnItem.block_allocations
            )
        )

    async def list_by_transaction(self, transaction_id: UUID) -> list[PurchaseReturn]:
        result = await self.session.execute(
            self._return_query()
            .where(PurchaseReturn.transaction_id == transaction_id)
            .order_by(
                PurchaseReturn.return_date,
                PurchaseReturn.return_time,
                PurchaseReturn.created_at,
                PurchaseReturn.id,
            )
        )
        return list(result.scalars().all())

    async def get_return_item(
        self,
        transaction_id: UUID,
        return_item_id: UUID,
    ) -> PurchaseReturnItem | None:
        result = await self.session.execute(
            select(PurchaseReturnItem)
            .join(PurchaseReturn, PurchaseReturn.id == PurchaseReturnItem.purchase_return_id)
            .where(
                PurchaseReturn.transaction_id == transaction_id,
                PurchaseReturnItem.id == return_item_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_returned_quantities(
        self,
        transaction_id: UUID,
    ) -> dict[UUID, Decimal]:
        result = await self.session.execute(
            select(PurchaseReturnItem.transaction_item_id, func.sum(PurchaseReturnItem.quantity))
            .join(PurchaseReturn, PurchaseReturn.id == PurchaseReturnItem.purchase_return_id)
            .where(PurchaseReturn.transaction_id == transaction_id)
            .group_by(PurchaseReturnItem.transaction_item_id)
        )
        return {
            transaction_item_id: quantity
            for transaction_item_id, quantity in result.all()
        }

    async def get_returned_quantities_by_block(
        self,
        transaction_id: UUID,
    ) -> dict[tuple[UUID, UUID], int]:
        result = await self.session.execute(
            select(
                PurchaseReturnItem.transaction_item_id,
                PurchaseReturnItemAllocation.block_id,
                func.sum(PurchaseReturnItemAllocation.quantity),
            )
            .join(PurchaseReturn, PurchaseReturn.id == PurchaseReturnItem.purchase_return_id)
            .join(
                PurchaseReturnItemAllocation,
                PurchaseReturnItemAllocation.purchase_return_item_id
                == PurchaseReturnItem.id,
            )
            .where(PurchaseReturn.transaction_id == transaction_id)
            .group_by(
                PurchaseReturnItem.transaction_item_id,
                PurchaseReturnItemAllocation.block_id,
            )
        )
        return {
            (transaction_item_id, block_id): quantity
            for transaction_item_id, block_id, quantity in result.all()
        }

    async def get_credit_amounts_by_item(
        self,
        transaction_id: UUID,
    ) -> dict[UUID, Decimal]:
        result = await self.session.execute(
            select(
                PurchaseReturnItem.transaction_item_id,
                func.sum(PurchaseReturnItem.credit_amount),
            )
            .join(PurchaseReturn, PurchaseReturn.id == PurchaseReturnItem.purchase_return_id)
            .where(PurchaseReturn.transaction_id == transaction_id)
            .group_by(PurchaseReturnItem.transaction_item_id)
        )
        return {
            transaction_item_id: amount
            for transaction_item_id, amount in result.all()
        }

    async def get_total_credit_by_transaction(self, transaction_id: UUID) -> Decimal:
        result = await self.session.execute(
            select(func.coalesce(func.sum(PurchaseReturnItem.credit_amount), 0))
            .join(PurchaseReturn, PurchaseReturn.id == PurchaseReturnItem.purchase_return_id)
            .where(PurchaseReturn.transaction_id == transaction_id)
        )
        return Decimal(result.scalar_one())

    async def create_return(self, data: dict) -> PurchaseReturn:
        purchase_return = PurchaseReturn(**data)
        self.session.add(purchase_return)
        await self.session.flush()
        return purchase_return

    async def create_item(self, data: dict) -> PurchaseReturnItem:
        item = PurchaseReturnItem(**data)
        self.session.add(item)
        await self.session.flush()
        return item

    async def create_allocation(self, data: dict) -> PurchaseReturnItemAllocation:
        allocation = PurchaseReturnItemAllocation(**data)
        self.session.add(allocation)
        await self.session.flush()
        return allocation