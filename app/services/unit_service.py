from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.core.logging import get_application_logger
from app.core.unit_of_work import UnitOfWork
from app.models.units import Unit
from app.models.user import User
from app.repositories.unit_repository import UnitRepository
from app.schemas.unit import UnitCreateRequest, UnitResponse, UnitUpdateRequest

app_logger = get_application_logger()
_UNIT_CONSTRAINTS = {"uq_units_name", "uq_units_abbreviation"}


def _is_unit_conflict(error: IntegrityError) -> bool:
    original_error = error.orig
    while original_error is not None:
        constraint_name = getattr(original_error, "constraint_name", None)
        if constraint_name is None:
            constraint_name = getattr(
                getattr(original_error, "diag", None),
                "constraint_name",
                None,
            )
        if constraint_name in _UNIT_CONSTRAINTS:
            return True
        original_error = original_error.__cause__ or original_error.__context__
    return False


def _is_unit_in_use(error: IntegrityError) -> bool:
    original_error = error.orig
    while original_error is not None:
        if (
            getattr(original_error, "sqlstate", None) == "23503"
            or getattr(original_error, "pgcode", None) == "23503"
        ):
            return True
        original_error = original_error.__cause__ or original_error.__context__
    return False


class UnitService:
    def __init__(self, repository: UnitRepository, unit_of_work: UnitOfWork):
        self.repository = repository
        self.unit_of_work = unit_of_work

    async def list_units(
        self,
        user: User,
        search: str | None = None,
    ) -> list[UnitResponse]:
        async with self.unit_of_work:
            units = await self.repository.list(search)
            app_logger.info(
                "units_listed",
                extra={"event": "units_listed", "user_id": user.id},
            )
            return [UnitResponse.model_validate(unit) for unit in units]

    async def get_unit(self, user: User, unit_id: UUID) -> UnitResponse:
        async with self.unit_of_work:
            unit = await self._get_or_raise(unit_id)
            response = UnitResponse.model_validate(unit)
            app_logger.info(
                "unit_retrieved",
                extra={"event": "unit_retrieved", "user_id": user.id},
            )
            return response

    async def create_unit(
        self,
        user: User,
        unit_data: UnitCreateRequest,
    ) -> UnitResponse:
        try:
            async with self.unit_of_work:
                unit = await self.repository.create(unit_data.model_dump())
                await self.unit_of_work.commit()
                response = UnitResponse.model_validate(unit)
                app_logger.info(
                    "unit_created",
                    extra={"event": "unit_created", "user_id": user.id},
                )
                return response
        except IntegrityError as exc:
            if _is_unit_conflict(exc):
                raise ConflictError(
                    "A unit with this name or abbreviation already exists."
                ) from exc
            raise

    async def update_unit(
        self,
        user: User,
        unit_id: UUID,
        unit_data: UnitUpdateRequest,
    ) -> UnitResponse:
        try:
            async with self.unit_of_work:
                unit = await self._get_or_raise(unit_id)
                for field, value in unit_data.model_dump(exclude_unset=True).items():
                    setattr(unit, field, value)
                unit = await self.repository.update(unit)
                await self.unit_of_work.commit()
                response = UnitResponse.model_validate(unit)
                app_logger.info(
                    "unit_updated",
                    extra={"event": "unit_updated", "user_id": user.id},
                )
                return response
        except IntegrityError as exc:
            if _is_unit_conflict(exc):
                raise ConflictError(
                    "A unit with this name or abbreviation already exists."
                ) from exc
            raise

    async def delete_unit(self, user: User, unit_id: UUID) -> None:
        try:
            async with self.unit_of_work:
                unit = await self._get_or_raise(unit_id)
                await self.repository.delete(unit)
                await self.unit_of_work.commit()
                app_logger.info(
                    "unit_deleted",
                    extra={"event": "unit_deleted", "user_id": user.id},
                )
        except IntegrityError as exc:
            if _is_unit_in_use(exc):
                raise ConflictError("A unit referenced by a product cannot be deleted.") from exc
            raise

    async def _get_or_raise(self, unit_id: UUID) -> Unit:
        unit = await self.repository.get_by_id(unit_id)
        if unit is None:
            raise ResourceNotFoundError("Unit not found.")
        return unit