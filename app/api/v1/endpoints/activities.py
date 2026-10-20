from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.dependencies.farm import get_owned_farm
from app.dependencies.services import get_activity_service
from app.models.farm import Farm
from app.schemas.activity import (
    ActivityFeedResponse,
    ActivityResponse,
    ActivitySummaryResponse,
)
from app.schemas.enums import ActivityCategory
from app.services.activity_service import ActivityService


router = APIRouter(
    prefix="/farms/{farm_id}/activities",
    tags=["Activities"],
)


@router.get("/summary", response_model=ActivitySummaryResponse)
async def get_activity_summary(
    farm: Farm = Depends(get_owned_farm),
    service: ActivityService = Depends(get_activity_service),
) -> ActivitySummaryResponse:
    return await service.get_summary_for_farm(farm)


@router.get("", response_model=ActivityFeedResponse)
async def list_activities(
    farm: Farm = Depends(get_owned_farm),
    service: ActivityService = Depends(get_activity_service),
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    before: Annotated[str | None, Query(max_length=256)] = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
    category: ActivityCategory | None = None,
    from_datetime: datetime | None = None,
    to_datetime: datetime | None = None,
) -> ActivityFeedResponse:
    return await service.list_for_farm(
        farm,
        limit=limit,
        before=before,
        search=search.strip() if search else None,
        category=category,
        from_datetime=from_datetime,
        to_datetime=to_datetime,
    )


@router.get("/{activity_id}", response_model=ActivityResponse)
async def get_activity(
    activity_id: UUID,
    farm: Farm = Depends(get_owned_farm),
    service: ActivityService = Depends(get_activity_service),
) -> ActivityResponse:
    return await service.get_for_farm(farm, activity_id)