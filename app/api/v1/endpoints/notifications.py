from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.dependencies.farm import get_owned_farm
from app.presentation.dependencies.services import get_notification_service
from app.models.farm import Farm
from app.schemas.enums import NotificationCategory
from app.schemas.notification import (
    NotificationListResponse,
    NotificationMutationResponse,
    NotificationResponse,
    NotificationUnreadCountResponse,
)
from app.services.notification_service import NotificationService

router = APIRouter(
    prefix="/farms/{farm_id}/notifications",
    tags=["Notifications"],
)


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
    unread_only: Annotated[bool, Query()] = False,
    category: Annotated[NotificationCategory | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> NotificationListResponse:
    return await service.list_notifications(
        farm,
        limit=limit,
        cursor=cursor,
        unread_only=unread_only,
        category=category,
    )


@router.get("/unread-count", response_model=NotificationUnreadCountResponse)
async def get_unread_notification_count(
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
) -> NotificationUnreadCountResponse:
    return await service.unread_count(farm)


@router.patch("/read-all", response_model=NotificationMutationResponse)
async def mark_all_notifications_read(
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
) -> NotificationMutationResponse:
    return await service.mark_all_read(farm)


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
async def mark_notification_read(
    notification_id: UUID,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
) -> NotificationResponse:
    return await service.mark_read(farm, notification_id)


@router.patch("/{notification_id}/archive", response_model=NotificationResponse)
async def archive_notification(
    notification_id: UUID,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
) -> NotificationResponse:
    return await service.archive(farm, notification_id)