from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.chicken_transaction_items import ChickenTransactionItem


class ChickenTransactionItemRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_batch(self, batch_id: UUID) -> list[ChickenTransactionItem]:
        result = await self.session.execute(
            select(ChickenTransactionItem)
            .options(
                selectinload(ChickenTransactionItem.transaction_item),
                selectinload(ChickenTransactionItem.block),
            )
            .where(ChickenTransactionItem.batch_id == batch_id)
            .order_by(ChickenTransactionItem.created_at, ChickenTransactionItem.id)
        )
        return list(result.scalars().all())

    async def get_by_transaction_item(
        self,
        transaction_item_id: UUID,
    ) -> ChickenTransactionItem | None:
        result = await self.session.execute(
            select(ChickenTransactionItem)
            .options(
                selectinload(ChickenTransactionItem.transaction_item),
                selectinload(ChickenTransactionItem.batch),
                selectinload(ChickenTransactionItem.block),
            )
            .where(ChickenTransactionItem.transaction_item_id == transaction_item_id)
        )
        return result.scalar_one_or_none()

    async def create(self, chicken_item_data: dict) -> ChickenTransactionItem:
        chicken_item = ChickenTransactionItem(**chicken_item_data)
        self.session.add(chicken_item)
        await self.session.flush()
        return chicken_item

    async def update(self, chicken_item: ChickenTransactionItem) -> ChickenTransactionItem:
        await self.session.flush()
        await self.session.refresh(chicken_item)
        return chicken_item

    async def delete(self, chicken_item: ChickenTransactionItem) -> None:
        await self.session.delete(chicken_item)
        await self.session.flush()
