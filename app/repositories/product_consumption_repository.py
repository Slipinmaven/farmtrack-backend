from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product_consumptions import ProductConsumption


class ProductConsumptionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, farm_id: UUID, data: dict) -> ProductConsumption:
        consumption = ProductConsumption(farm_id=farm_id, **data)
        self.session.add(consumption)
        await self.session.flush()
        return consumption

    async def list_by_farm(
        self,
        farm_id: UUID,
        *,
        product_id: UUID | None = None,
        block_id: UUID | None = None,
        batch_id: UUID | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[ProductConsumption]:
        query = select(ProductConsumption).where(
            ProductConsumption.farm_id == farm_id
        )
        if product_id is not None:
            query = query.where(ProductConsumption.product_id == product_id)
        if block_id is not None:
            query = query.where(ProductConsumption.block_id == block_id)
        if batch_id is not None:
            query = query.where(ProductConsumption.batch_id == batch_id)
        if from_date is not None:
            query = query.where(ProductConsumption.consumption_date >= from_date)
        if to_date is not None:
            query = query.where(ProductConsumption.consumption_date <= to_date)
        result = await self.session.execute(
            query.order_by(
                ProductConsumption.consumption_date.desc(),
                ProductConsumption.created_at.desc(),
                ProductConsumption.id,
            )
        )
        return list(result.scalars().all())