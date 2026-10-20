from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.product_units import ProductUnit
from app.models.units import Unit


class ProductUnitRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_product_and_unit(
        self,
        product_id: UUID,
        unit_id: UUID,
    ) -> ProductUnit | None:
        result = await self.session.execute(
            select(ProductUnit).where(
                ProductUnit.product_id == product_id,
                ProductUnit.unit_id == unit_id,
            ).options(joinedload(ProductUnit.unit))
        )
        return result.scalar_one_or_none()

    async def get_base_unit_for_product(self, product_id: UUID) -> Unit | None:
        result = await self.session.execute(
            select(Unit)
            .join(ProductUnit, ProductUnit.unit_id == Unit.id)
            .where(
                ProductUnit.product_id == product_id,
                ProductUnit.is_base_unit.is_(True),
            )
        )
        return result.scalar_one_or_none()