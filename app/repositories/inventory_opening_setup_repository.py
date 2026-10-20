from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inventory_opening_setup import InventoryOpeningSetup


class InventoryOpeningSetupRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_for_species(
        self,
        farm_id: UUID,
        species: str,
    ) -> InventoryOpeningSetup | None:
        result = await self.session.execute(
            select(InventoryOpeningSetup).where(
                InventoryOpeningSetup.farm_id == farm_id,
                InventoryOpeningSetup.species == species,
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        farm_id: UUID,
        species: str,
        setup_date: date,
    ) -> InventoryOpeningSetup:
        record = InventoryOpeningSetup(
            farm_id=farm_id,
            species=species,
            setup_date=setup_date,
        )
        self.session.add(record)
        await self.session.flush()
        return record
