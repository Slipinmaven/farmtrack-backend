from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_security_settings import AppSecuritySettings
from app.schemas.security_settings import SecuritySettingsUpdate


class AppSecuritySettingsRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_user_id(self, user_id: UUID) -> AppSecuritySettings | None:
        result = await self.session.execute(
            select(AppSecuritySettings).where(
                AppSecuritySettings.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def create_for_user(self, user_id: UUID) -> AppSecuritySettings:
        settings = AppSecuritySettings(user_id=user_id)
        self.session.add(settings)
        await self.session.flush()
        await self.session.refresh(settings)
        return settings

    async def update(
        self,
        settings: AppSecuritySettings,
        update_data: SecuritySettingsUpdate,
    ) -> AppSecuritySettings:
        for field, value in update_data.model_dump(exclude_unset=True).items():
            setattr(settings, field, value)

        await self.session.flush()
        await self.session.refresh(settings)
        return settings