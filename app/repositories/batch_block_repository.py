from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.batch_blocks import BatchBlock


class BatchBlockRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_batch(self, batch_id: UUID) -> list[BatchBlock]:
        result = await self.session.execute(
            select(BatchBlock)
            .where(BatchBlock.batch_id == batch_id)
            .order_by(BatchBlock.created_at, BatchBlock.id)
        )
        return list(result.scalars().all())

    async def list_by_block(self, block_id: UUID) -> list[BatchBlock]:
        result = await self.session.execute(
            select(BatchBlock)
            .where(BatchBlock.block_id == block_id)
            .order_by(BatchBlock.created_at, BatchBlock.id)
        )
        return list(result.scalars().all())

    async def get_by_id(self, batch_block_id: UUID) -> BatchBlock | None:
        result = await self.session.execute(
            select(BatchBlock).where(BatchBlock.id == batch_block_id)
        )
        return result.scalar_one_or_none()

    async def get_by_batch_and_block(
        self,
        batch_id: UUID,
        block_id: UUID,
    ) -> BatchBlock | None:
        result = await self.session.execute(
            select(BatchBlock)
            .where(
                BatchBlock.batch_id == batch_id,
                BatchBlock.block_id == block_id,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_total_quantity_by_block(self, block_id: UUID) -> int:
        result = await self.session.execute(
            select(func.coalesce(func.sum(BatchBlock.quantity), 0)).where(
                BatchBlock.block_id == block_id
            )
        )
        return result.scalar_one()

    async def get_total_quantities_by_blocks(
        self,
        block_ids: set[UUID],
    ) -> dict[UUID, int]:
        if not block_ids:
            return {}
        result = await self.session.execute(
            select(
                BatchBlock.block_id,
                func.sum(BatchBlock.quantity),
            )
            .where(BatchBlock.block_id.in_(block_ids))
            .group_by(BatchBlock.block_id)
        )
        return {
            block_id: quantity
            for block_id, quantity in result.all()
        }

    async def create(self, assignment_data: dict) -> BatchBlock:
        assignment = BatchBlock(**assignment_data)
        self.session.add(assignment)
        await self.session.flush()
        return assignment

    async def update(self, assignment: BatchBlock) -> BatchBlock:
        await self.session.flush()
        await self.session.refresh(assignment)
        return assignment

    async def delete(self, assignment: BatchBlock) -> None:
        await self.session.delete(assignment)
        await self.session.flush()
