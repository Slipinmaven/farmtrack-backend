from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chicken_losses import ChickenLoss


class ChickenLossRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_farm(
        self,
        farm_id: UUID,
        *,
        batch_id: UUID | None = None,
        block_id: UUID | None = None,
        reason: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[ChickenLoss]:
        query = select(ChickenLoss).where(ChickenLoss.farm_id == farm_id)
        if batch_id is not None:
            query = query.where(ChickenLoss.batch_id == batch_id)
        if block_id is not None:
            query = query.where(ChickenLoss.block_id == block_id)
        if reason is not None:
            query = query.where(ChickenLoss.reason == reason)
        if from_date is not None:
            query = query.where(ChickenLoss.loss_date >= from_date)
        if to_date is not None:
            query = query.where(ChickenLoss.loss_date <= to_date)
        result = await self.session.execute(
            query.order_by(
                ChickenLoss.loss_date.desc(),
                ChickenLoss.created_at.desc(),
                ChickenLoss.id,
            )
        )
        return list(result.scalars().all())

    async def create_many(
        self,
        farm_id: UUID,
        records: list[dict],
    ) -> list[ChickenLoss]:
        losses = [ChickenLoss(farm_id=farm_id, **record) for record in records]
        self.session.add_all(losses)
        await self.session.flush()
        return losses