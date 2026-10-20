from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from sqlalchemy import select
from typing import Optional

from app.core.exceptions import FarmSettingsNotFoundError
from app.models.farm_settings import FarmSettings
from app.schemas.farm import FarmSettingsUpdate, FarmSettingsCreate

class FarmSettingsRepository:
    
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_farm_settings(self, farm_id: UUID) ->FarmSettings| None:
        result = await self.session.execute(select(FarmSettings).where(FarmSettings.farm_id == farm_id))
        return result.scalar_one_or_none()

    async def create(
        self,
        farm_id: UUID,
        settings_data: FarmSettingsCreate,
    ) -> FarmSettings:
        farm_settings = FarmSettings(
            farm_id=farm_id,
            **settings_data.model_dump(exclude_unset=True),
        )
        self.session.add(farm_settings)
        await self.session.flush()
        return farm_settings

    async def update_farm_settings(
        self,
        farm_id: UUID,
        settings_data: FarmSettingsUpdate,
    ) -> FarmSettings:
        farm_settings = await self.get_farm_settings(farm_id)

        if not farm_settings:
            raise FarmSettingsNotFoundError(farm_id)

        update_data = settings_data.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            setattr(farm_settings, field, value)

        await self.session.flush()
        await self.session.refresh(farm_settings)

        return farm_settings

