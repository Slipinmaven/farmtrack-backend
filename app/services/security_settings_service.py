from uuid import UUID

from app.core.logging import get_application_logger
from app.core.unit_of_work import UnitOfWork
from app.models.user import User
from app.repositories.app_security_settings_repository import (
    AppSecuritySettingsRepository,
)
from app.schemas.security_settings import (
    SecuritySettingsResponse,
    SecuritySettingsUpdate,
)

app_logger = get_application_logger()


class SecuritySettingsService:
    def __init__(
        self,
        repository: AppSecuritySettingsRepository,
        unit_of_work: UnitOfWork,
    ):
        self.repository = repository
        self.unit_of_work = unit_of_work

    async def get_for_user(self, user: User) -> SecuritySettingsResponse:
        async with self.unit_of_work:
            settings = await self.repository.get_by_user_id(user.id)
            if settings is None:
                settings = await self.repository.create_for_user(user.id)

            response = SecuritySettingsResponse.model_validate(
                settings,
                from_attributes=True,
            )
            await self.unit_of_work.commit()
            app_logger.info(
                "security_settings_retrieved",
                extra={"event": "security_settings_retrieved", "user_id": user.id},
            )
            return response

    async def update_for_user(
        self,
        user: User,
        update_data: SecuritySettingsUpdate,
    ) -> SecuritySettingsResponse:
        async with self.unit_of_work:
            settings = await self.repository.get_by_user_id(user.id)
            if settings is None:
                settings = await self.repository.create_for_user(user.id)

            settings = await self.repository.update(settings, update_data)
            response = SecuritySettingsResponse.model_validate(
                settings,
                from_attributes=True,
            )
            await self.unit_of_work.commit()
            app_logger.info(
                "security_settings_updated",
                extra={"event": "security_settings_updated", "user_id": user.id},
            )
            return response