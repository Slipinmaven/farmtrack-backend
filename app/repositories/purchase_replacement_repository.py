from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.purchase_replacement_item_allocations import (
    PurchaseReplacementItemAllocation,
)
from app.models.purchase_replacement_items import PurchaseReplacementItem
from app.models.purchase_replacements import PurchaseReplacement


class PurchaseReplacementRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    def _replacement_query(self):
        return select(PurchaseReplacement).options(
            selectinload(PurchaseReplacement.items).selectinload(
                PurchaseReplacementItem.block_allocations
            ),
            selectinload(PurchaseReplacement.items).selectinload(
                PurchaseReplacementItem.batch
            ),
        )

    async def list_by_transaction(
        self,
        transaction_id: UUID,
    ) -> list[PurchaseReplacement]:
        result = await self.session.execute(
            self._replacement_query()
            .where(PurchaseReplacement.transaction_id == transaction_id)
            .order_by(
                PurchaseReplacement.replacement_date,
                PurchaseReplacement.replacement_time,
                PurchaseReplacement.id,
            )
        )
        return list(result.scalars().all())

    async def get_credit_applied_by_return_item(
        self,
        return_item_id: UUID,
    ) -> Decimal:
        result = await self.session.execute(
            select(
                func.coalesce(func.sum(PurchaseReplacementItem.credit_applied_amount), 0)
            ).where(PurchaseReplacementItem.purchase_return_item_id == return_item_id)
        )
        return Decimal(result.scalar_one())

    async def get_total_credit_applied_by_transaction(
        self,
        transaction_id: UUID,
    ) -> Decimal:
        result = await self.session.execute(
            select(
                func.coalesce(func.sum(PurchaseReplacementItem.credit_applied_amount), 0)
            )
            .join(
                PurchaseReplacement,
                PurchaseReplacement.id == PurchaseReplacementItem.purchase_replacement_id,
            )
            .where(PurchaseReplacement.transaction_id == transaction_id)
        )
        return Decimal(result.scalar_one())

    async def create_replacement(self, data: dict) -> PurchaseReplacement:
        replacement = PurchaseReplacement(**data)
        self.session.add(replacement)
        await self.session.flush()
        return replacement

    async def create_item(self, data: dict) -> PurchaseReplacementItem:
        item = PurchaseReplacementItem(**data)
        self.session.add(item)
        await self.session.flush()
        return item

    async def create_allocation(self, data: dict) -> PurchaseReplacementItemAllocation:
        allocation = PurchaseReplacementItemAllocation(**data)
        self.session.add(allocation)
        await self.session.flush()
        return allocation