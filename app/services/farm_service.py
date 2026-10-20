
from sqlalchemy.exc import IntegrityError

from app.repositories.farm_repository import FarmRepository
from app.models.farm import Farm
from app.core.unit_of_work import UnitOfWork
from app.core.exceptions import ConflictError
from app.schemas.farm import (
    FarmCreateRequest,
    FarmResponse,
    FarmSettingsCreate,
    FarmSettingsResponse,
    FarmSettingsUpdate,
    FarmUpdateRequest,
)
from app.repositories.farm_settings_repository import FarmSettingsRepository
from app.core.logging import get_application_logger
from app.core.defaults import DEFAULT_FARM_SETTINGS
from app.models.user import User
from app.schemas.enums import ActivityEntityType, ActivityType
from app.services.activity_service import ActivityService
from app.services.activity_details import activity_field_changes

app_logger = get_application_logger()


def _is_farm_name_conflict(error: IntegrityError) -> bool:
    original_error = error.orig
    while original_error is not None:
        constraint_name = getattr(original_error, "constraint_name", None)
        if constraint_name is None:
            constraint_name = getattr(
                getattr(original_error, "diag", None),
                "constraint_name",
                None,
            )
        if constraint_name == "uq_farms_owner_id_name":
            return True
        original_error = original_error.__cause__ or original_error.__context__
    return False


class FarmService:
    def __init__(
            self, 
            farm_repository: FarmRepository,
            farm_settings_repository: FarmSettingsRepository,
            activity_service: ActivityService,
            unit_of_work: UnitOfWork
        ):
        self.farm_repository = farm_repository
        self.farm_settings_repository = farm_settings_repository
        self.activity_service = activity_service
        self.unit_of_work = unit_of_work

    async def get_user_farms(self, user: User, search: str | None = None, is_active: bool | None = None) -> list[Farm]:
        async with self.unit_of_work:
            farms = await self.farm_repository.get_user_farms(
                user.id,
                search=search,
                is_active=is_active,
            )
            app_logger.info(
                "farms_listed",
                extra={"event": "farms_listed", "user_id": user.id},
            )
            return farms

    async def update_farm(
        self,
        farm: Farm,
        farm_data: FarmUpdateRequest,
    ) -> FarmResponse:
        try:
            async with self.unit_of_work:
                update_data = farm_data.model_dump(exclude_unset=True)
                before_values = {
                    field: getattr(farm, field) for field in update_data
                }
                for field, value in update_data.items():
                    setattr(farm, field, value)
                changes = activity_field_changes(
                    before_values,
                    {field: getattr(farm, field) for field in update_data},
                )

                await self.farm_repository.update(farm)
                if changes:
                    await self.activity_service.record(
                        farm_id=farm.id,
                        user_id=farm.owner_id,
                        activity_type=ActivityType.FARM_UPDATED,
                        entity_type=ActivityEntityType.FARM,
                        entity_id=farm.id,
                        details={"name": farm.name, "changes": changes},
                    )
                settings = await self.farm_settings_repository.get_farm_settings(farm.id)
                response = FarmResponse(
                    id=farm.id,
                    owner_id=farm.owner_id,
                    name=farm.name,
                    description=farm.description,
                    location=farm.location,
                    phone_number=farm.phone_number,
                    email=farm.email,
                    maximum_chicken_capacity=farm.maximum_chicken_capacity,
                    is_active=farm.is_active,
                    created_at=farm.created_at,
                    updated_at=farm.updated_at,
                    settings=(
                        FarmSettingsResponse.model_validate(
                            settings,
                            from_attributes=True,
                        )
                        if settings is not None
                        else None
                    ),
                )
                await self.unit_of_work.commit()
                app_logger.info(
                    "farm_updated",
                    extra={"event": "farm_updated", "user_id": farm.owner_id, "farm_id": farm.id},
                )
                return response
        except IntegrityError as exc:
            if _is_farm_name_conflict(exc):
                raise ConflictError(
                    "A farm with this name already exists for your account."
                ) from exc
            raise

    async def update_farm_settings(
        self,
        farm: Farm,
        settings_data: FarmSettingsUpdate,
    ) -> FarmSettingsResponse:
        async with self.unit_of_work:
            current_settings = await self.farm_settings_repository.get_farm_settings(
                farm.id
            )
            update_data = settings_data.model_dump(exclude_unset=True)
            before_values = {
                field: getattr(current_settings, field)
                for field in update_data
                if current_settings is not None
            }
            settings = await self.farm_settings_repository.update_farm_settings(
                farm.id,
                settings_data,
            )
            changes = activity_field_changes(
                before_values,
                {field: getattr(settings, field) for field in update_data},
            )
            response = FarmSettingsResponse.model_validate(
                settings,
                from_attributes=True,
            )
            if changes:
                await self.activity_service.record(
                    farm_id=farm.id,
                    user_id=farm.owner_id,
                    activity_type=ActivityType.FARM_SETTINGS_UPDATED,
                    entity_type=ActivityEntityType.FARM,
                    entity_id=farm.id,
                    details={
                        "farm_name": farm.name,
                        "changes": changes,
                    },
                )
            await self.unit_of_work.commit()
            app_logger.info(
                "farm_settings_updated",
                extra={"event": "farm_settings_updated", "user_id": farm.owner_id, "farm_id": farm.id},
            )
            return response

    async def delete_farm(self, farm: Farm) -> None:
        async with self.unit_of_work:
            await self.farm_repository.delete(farm)
            await self.unit_of_work.commit()
            app_logger.info(
                "farm_deleted",
                extra={"event": "farm_deleted", "user_id": farm.owner_id, "farm_id": farm.id},
            )
    
    async def get_farm_with_settings(
        self,
        farm: Farm,
    ) -> FarmResponse:
        async with self.unit_of_work:
            farm_settings = await self.farm_settings_repository.get_farm_settings(
                farm.id
            )

            if not farm_settings:
                app_logger.warning(
                    f"Farm settings not found for farm: {farm.id}"
                )

            app_logger.info(
                "farm_retrieved",
                extra={"event": "farm_retrieved", "user_id": farm.owner_id, "farm_id": farm.id},
            )

            return FarmResponse(
                id=farm.id,
                owner_id=farm.owner_id,
                name=farm.name,
                description=farm.description,
                location=farm.location,
                phone_number=farm.phone_number,
                email=farm.email,
                maximum_chicken_capacity=farm.maximum_chicken_capacity,
                is_active=farm.is_active,
                created_at=farm.created_at,
                updated_at=farm.updated_at,
                settings=(
                    FarmSettingsResponse.model_validate(
                        farm_settings, from_attributes=True
                    )
                    if farm_settings is not None
                    else None
                ),
            )

    async def create_farm(
        self,
        user: User,
        farm_data: FarmCreateRequest,
    ):
        try:
            async with self.unit_of_work:
                settings_data = farm_data.settings

                farm_payload = farm_data.model_dump(exclude={"settings"})
                farm_payload["owner_id"] = user.id

                farm = await self.farm_repository.create(
                    farm_data=farm_payload
                )

                settings_payload = {
                    **DEFAULT_FARM_SETTINGS,
                    **(
                        settings_data.model_dump(exclude_unset=True)
                        if settings_data is not None
                        else {}
                    ),
                }

                settings = await self.farm_settings_repository.create(
                    farm_id=farm.id,
                    settings_data=FarmSettingsCreate.model_validate(settings_payload),
                )

                await self.activity_service.record(
                    farm_id=farm.id,
                    user_id=user.id,
                    activity_type=ActivityType.FARM_CREATED,
                    entity_type=ActivityEntityType.FARM,
                    entity_id=farm.id,
                    details={
                        "name": farm.name,
                        "description": farm.description,
                        "location": farm.location,
                        "phone_number": farm.phone_number,
                        "email": farm.email,
                        "maximum_chicken_capacity": farm.maximum_chicken_capacity,
                        "settings": {
                            "currency": settings.currency,
                            "timezone": settings.timezone,
                            "theme_mode": settings.theme_mode,
                        },
                    },
                )

                response = FarmResponse(
                    id=farm.id,
                    owner_id=farm.owner_id,
                    name=farm.name,
                    description=farm.description,
                    location=farm.location,
                    phone_number=farm.phone_number,
                    email=farm.email,
                    maximum_chicken_capacity=farm.maximum_chicken_capacity,
                    is_active=farm.is_active,
                    created_at=farm.created_at,
                    updated_at=farm.updated_at,
                    settings=FarmSettingsResponse.model_validate(
                        settings,
                        from_attributes=True,
                    ),
                )
                await self.unit_of_work.commit()
                app_logger.info(
                    "farm_created",
                    extra={"event": "farm_created", "user_id": user.id, "farm_id": farm.id},
                )
                return response
        except IntegrityError as exc:
            if _is_farm_name_conflict(exc):
                raise ConflictError("A farm with this name already exists for your account.") from exc
            raise