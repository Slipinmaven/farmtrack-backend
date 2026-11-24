from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.dependencies.farm import get_owned_farm
from app.dependencies.auth import get_current_user
from app.presentation.dependencies.services import get_reminder_service
from app.models.farm import Farm
from app.models.user import User
from app.schemas.enums import ReminderStatus
from app.schemas.reminder import (
    ReminderCreateRequest,
    ReminderResponse,
    ReminderRescheduleRequest,
)
from app.services.reminder_service import ReminderService


router = APIRouter(prefix="/farms/{farm_id}/reminders", tags=["Reminders"])


@router.get("", response_model=list[ReminderResponse])
async def list_reminders(
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[ReminderService, Depends(get_reminder_service)],
) -> list[ReminderResponse]:
    return await service.list_for_farm(farm)


@router.post("", response_model=ReminderResponse, status_code=201)
async def create_reminder(
    request: ReminderCreateRequest,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ReminderService, Depends(get_reminder_service)],
) -> ReminderResponse:
    return await service.create(
        farm,
        request,
        created_by_user_id=current_user.id,
    )


@router.get("/{reminder_id}", response_model=ReminderResponse)
async def get_reminder(
    reminder_id: UUID,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[ReminderService, Depends(get_reminder_service)],
) -> ReminderResponse:
    return await service.get_for_farm(farm, reminder_id)


@router.patch("/{reminder_id}/reschedule", response_model=ReminderResponse)
async def reschedule_reminder(
    reminder_id: UUID,
    request: ReminderRescheduleRequest,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[ReminderService, Depends(get_reminder_service)],
) -> ReminderResponse:
    return await service.reschedule(farm, reminder_id, request)


@router.patch("/{reminder_id}/reopen", response_model=ReminderResponse)
async def reopen_reminder(
    reminder_id: UUID,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[ReminderService, Depends(get_reminder_service)],
) -> ReminderResponse:
    return await service.reopen(farm, reminder_id)


@router.patch("/{reminder_id}/complete", response_model=ReminderResponse)
async def complete_reminder(
    reminder_id: UUID,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[ReminderService, Depends(get_reminder_service)],
) -> ReminderResponse:
    return await service.update_status(farm, reminder_id, ReminderStatus.COMPLETED)


@router.patch("/{reminder_id}/cancel", response_model=ReminderResponse)
async def cancel_reminder(
    reminder_id: UUID,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[ReminderService, Depends(get_reminder_service)],
) -> ReminderResponse:
    return await service.update_status(farm, reminder_id, ReminderStatus.CANCELLED)