from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.units import Unit


class UnitRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list(self, search: str | None = None) -> list[Unit]:
        query = select(Unit)
        if search is not None:
            term = f"%{search.strip()}%"
            query = query.where(
                or_(Unit.name.ilike(term), Unit.abbreviation.ilike(term))
            )
        result = await self.session.execute(query.order_by(Unit.name, Unit.id))
        return list(result.scalars().all())

    async def get_by_id(self, unit_id: UUID) -> Unit | None:
        result = await self.session.execute(select(Unit).where(Unit.id == unit_id))
        return result.scalar_one_or_none()

    async def create(self, unit_data: dict) -> Unit:
        unit = Unit(**unit_data)
        self.session.add(unit)
        await self.session.flush()
        return unit

    async def update(self, unit: Unit) -> Unit:
        await self.session.flush()
        await self.session.refresh(unit)
        return unit

    async def delete(self, unit: Unit) -> None:
        await self.session.delete(unit)
        await self.session.flush()