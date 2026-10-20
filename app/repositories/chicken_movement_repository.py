from datetime import date
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.blocks import Block
from app.models.chicken_batches import ChickenBatch
from app.models.chicken_movements import ChickenMovement


class ChickenMovementRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_farm(
        self,
        farm_id: UUID,
        *,
        batch_id: UUID | None = None,
        from_block_id: UUID | None = None,
        to_block_id: UUID | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[ChickenMovement]:
        query = select(ChickenMovement).where(ChickenMovement.farm_id == farm_id)
        if batch_id is not None:
            query = query.where(ChickenMovement.batch_id == batch_id)
        if from_block_id is not None:
            query = query.where(ChickenMovement.from_block_id == from_block_id)
        if to_block_id is not None:
            query = query.where(ChickenMovement.to_block_id == to_block_id)
        if from_date is not None:
            query = query.where(ChickenMovement.movement_date >= from_date)
        if to_date is not None:
            query = query.where(ChickenMovement.movement_date <= to_date)
        result = await self.session.execute(
            query.order_by(
                ChickenMovement.movement_date.desc(),
                ChickenMovement.created_at.desc(),
                ChickenMovement.id,
            )
        )
        return list(result.scalars().all())

    async def list_block_history(
        self,
        farm_id: UUID,
        block_id: UUID,
        *,
        direction: str = "all",
        search: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[tuple[ChickenMovement, str, str, str]], int]:
        from_block = aliased(Block)
        to_block = aliased(Block)
        conditions = [
            ChickenMovement.farm_id == farm_id,
            or_(
                ChickenMovement.from_block_id == block_id,
                ChickenMovement.to_block_id == block_id,
            ),
        ]
        if direction == "incoming":
            conditions.append(ChickenMovement.to_block_id == block_id)
        elif direction == "outgoing":
            conditions.append(ChickenMovement.from_block_id == block_id)
        if from_date is not None:
            conditions.append(ChickenMovement.movement_date >= from_date)
        if to_date is not None:
            conditions.append(ChickenMovement.movement_date <= to_date)
        if search:
            term = f"%{search.strip()}%"
            conditions.append(
                or_(
                    ChickenBatch.name.ilike(term),
                    from_block.name.ilike(term),
                    to_block.name.ilike(term),
                    ChickenMovement.reason.ilike(term),
                    ChickenMovement.notes.ilike(term),
                )
            )

        joins = (
            select(
                ChickenMovement,
                ChickenBatch.name,
                from_block.name,
                to_block.name,
            )
            .join(ChickenBatch, ChickenBatch.id == ChickenMovement.batch_id)
            .join(from_block, from_block.id == ChickenMovement.from_block_id)
            .join(to_block, to_block.id == ChickenMovement.to_block_id)
            .where(*conditions)
        )
        result = await self.session.execute(
            joins.order_by(
                ChickenMovement.movement_date.desc(),
                ChickenMovement.created_at.desc(),
                ChickenMovement.id,
            )
            .offset(offset)
            .limit(limit)
        )
        count_result = await self.session.execute(
            select(func.count(ChickenMovement.id))
            .select_from(ChickenMovement)
            .join(ChickenBatch, ChickenBatch.id == ChickenMovement.batch_id)
            .join(from_block, from_block.id == ChickenMovement.from_block_id)
            .join(to_block, to_block.id == ChickenMovement.to_block_id)
            .where(*conditions)
        )
        return list(result.tuples().all()), int(count_result.scalar_one())

    async def create(self, farm_id: UUID, data: dict) -> ChickenMovement:
        movement = ChickenMovement(farm_id=farm_id, **data)
        self.session.add(movement)
        await self.session.flush()
        return movement