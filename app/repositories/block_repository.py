from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.batch_blocks import BatchBlock
from app.models.blocks import Block
from app.models.chicken_batches import ChickenBatch
from app.schemas.enums import ChickenBatchStatus


class BlockRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_occupied_chickens(self, farm_id: UUID, block_id: UUID) -> int:
        result = await self.session.execute(
            select(func.coalesce(func.sum(BatchBlock.quantity), 0))
            .join(Block, Block.id == BatchBlock.block_id)
            .where(Block.farm_id == farm_id, Block.id == block_id)
        )
        return int(result.scalar_one())

    async def list_batch_occupancy(
        self,
        farm_id: UUID,
        block_id: UUID,
    ) -> list[BatchBlock]:
        result = await self.session.execute(
            select(BatchBlock)
            .join(Block, Block.id == BatchBlock.block_id)
            .join(ChickenBatch, ChickenBatch.id == BatchBlock.batch_id)
            .options(selectinload(BatchBlock.batch))
            .where(
                Block.farm_id == farm_id,
                Block.id == block_id,
                BatchBlock.quantity > 0,
            )
            .order_by(ChickenBatch.name, ChickenBatch.id)
        )
        return list(result.scalars().all())

    async def get_occupancy_by_farm(self, farm_id: UUID) -> dict[UUID, int]:
        result = await self.session.execute(
            select(BatchBlock.block_id, func.sum(BatchBlock.quantity))
            .join(Block, Block.id == BatchBlock.block_id)
            .where(Block.farm_id == farm_id)
            .group_by(BatchBlock.block_id)
        )
        return {block_id: int(quantity) for block_id, quantity in result.all()}

    async def list_by_farm(
        self,
        farm_id: UUID,
        search: str | None = None,
        is_active: bool | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Block]:
        query = select(Block).where(Block.farm_id == farm_id)

        if search is not None:
            term = f"%{search.strip()}%"
            query = query.where(
                or_(Block.name.ilike(term), Block.description.ilike(term))
            )

        if is_active is not None:
            query = query.where(Block.is_active == is_active)

        query = query.order_by(Block.name, Block.id)
        if offset:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def list_active_with_batch_stock(
        self,
        farm_id: UUID,
        batch_id: UUID,
        *,
        search: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[tuple[Block, int]]:
        query = (
            select(Block, BatchBlock.quantity)
            .join(BatchBlock, BatchBlock.block_id == Block.id)
            .where(
                Block.farm_id == farm_id,
                Block.is_active.is_(True),
                BatchBlock.batch_id == batch_id,
                BatchBlock.quantity > 0,
            )
        )
        if search is not None:
            term = f"%{search.strip()}%"
            query = query.where(
                or_(Block.name.ilike(term), Block.description.ilike(term))
            )
        query = query.order_by(Block.name, Block.id)
        if offset:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        result = await self.session.execute(query)
        return [(block, int(quantity)) for block, quantity in result.all()]

    async def list_active_with_chicken_stock(
        self,
        farm_id: UUID,
        *,
        search: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[tuple[Block, int]]:
        query = (
            select(Block, func.sum(BatchBlock.quantity))
            .join(BatchBlock, BatchBlock.block_id == Block.id)
            .join(ChickenBatch, ChickenBatch.id == BatchBlock.batch_id)
            .where(
                Block.farm_id == farm_id,
                Block.is_active.is_(True),
                ChickenBatch.status == ChickenBatchStatus.ACTIVE,
                BatchBlock.quantity > 0,
            )
        )
        if search is not None:
            term = f"%{search.strip()}%"
            query = query.where(
                or_(Block.name.ilike(term), Block.description.ilike(term))
            )
        query = (
            query.group_by(Block.id)
            .order_by(Block.name, Block.id)
        )
        if offset:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        result = await self.session.execute(query)
        return [(block, int(quantity)) for block, quantity in result.all()]

    async def get_by_id(self, farm_id: UUID, block_id: UUID) -> Block | None:
        result = await self.session.execute(
            select(Block).where(Block.farm_id == farm_id, Block.id == block_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_for_update(self, farm_id: UUID, block_id: UUID) -> Block | None:
        result = await self.session.execute(
            select(Block)
            .where(Block.farm_id == farm_id, Block.id == block_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def create(self, farm_id: UUID, block_data: dict) -> Block:
        block = Block(farm_id=farm_id, **block_data)
        self.session.add(block)
        await self.session.flush()
        return block

    async def update(self, block: Block) -> Block:
        await self.session.flush()
        await self.session.refresh(block)
        return block

    async def delete(self, block: Block) -> None:
        await self.session.execute(
            delete(BatchBlock).where(BatchBlock.block_id == block.id)
        )
        await self.session.execute(
            delete(Block).where(
                Block.id == block.id,
                Block.farm_id == block.farm_id,
            )
        )
        await self.session.flush()