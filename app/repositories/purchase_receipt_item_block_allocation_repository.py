from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.purchase_receipt_item_block_allocations import (
    PurchaseReceiptItemBlockAllocation,
)


class PurchaseReceiptItemBlockAllocationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_receipt_item(
        self,
        receipt_item_id: UUID,
    ) -> list[PurchaseReceiptItemBlockAllocation]:
        result = await self.session.execute(
            select(PurchaseReceiptItemBlockAllocation)
            .where(
                PurchaseReceiptItemBlockAllocation.purchase_receipt_item_id
                == receipt_item_id
            )
            .order_by(PurchaseReceiptItemBlockAllocation.created_at)
        )
        return list(result.scalars().all())

    async def create(
        self,
        allocation_data: dict,
    ) -> PurchaseReceiptItemBlockAllocation:
        allocation = PurchaseReceiptItemBlockAllocation(**allocation_data)
        self.session.add(allocation)
        await self.session.flush()
        return allocation
