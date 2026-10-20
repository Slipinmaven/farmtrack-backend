from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.egg_losses import EggLoss
from app.schemas.enums import EggLossReason


class EggLossRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_total_base_quantity(
        self,
        farm_id: UUID,
        product_id: UUID,
    ) -> Decimal:
        result = await self.session.execute(
            select(
                func.coalesce(
                    func.sum(EggLoss.quantity * EggLoss.conversion_factor),
                    0,
                )
            ).where(
                EggLoss.farm_id == farm_id,
                EggLoss.product_id == product_id,
            )
        )
        return Decimal(result.scalar_one())

    async def get_totals_by_farm(self, farm_id: UUID) -> dict[UUID, Decimal]:
        result = await self.session.execute(
            select(
                EggLoss.product_id,
                func.coalesce(
                    func.sum(EggLoss.quantity * EggLoss.conversion_factor),
                    0,
                ),
            )
            .where(EggLoss.farm_id == farm_id)
            .group_by(EggLoss.product_id)
        )
        return {
            product_id: Decimal(quantity)
            for product_id, quantity in result.all()
        }

    async def list_by_farm(
        self,
        farm_id: UUID,
        *,
        product_id: UUID | None = None,
        reason: EggLossReason | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[EggLoss]:
        query = select(EggLoss).where(EggLoss.farm_id == farm_id)
        if product_id is not None:
            query = query.where(EggLoss.product_id == product_id)
        if reason is not None:
            query = query.where(EggLoss.reason == reason)
        if from_date is not None:
            query = query.where(EggLoss.loss_date >= from_date)
        if to_date is not None:
            query = query.where(EggLoss.loss_date <= to_date)
        result = await self.session.execute(
            query.order_by(
                EggLoss.loss_date.desc(),
                EggLoss.created_at.desc(),
                EggLoss.id,
            )
        )
        return list(result.scalars().all())

    async def create(self, farm_id: UUID, data: dict) -> EggLoss:
        loss = EggLoss(farm_id=farm_id, **data)
        self.session.add(loss)
        await self.session.flush()
        return loss