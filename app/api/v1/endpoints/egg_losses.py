from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.dependencies.farm import get_owned_farm
from app.dependencies.services import get_egg_loss_service
from app.models.farm import Farm
from app.schemas.egg_loss import (
    EggLossBatchCreateRequest,
    EggLossCreateRequest,
    EggLossResponse,
)
from app.schemas.enums import EggLossReason
from app.services.egg_loss_service import EggLossService

router = APIRouter(
    prefix="/farms/{farm_id}/egg-losses",
    tags=["Egg Losses"],
)


@router.get("", response_model=list[EggLossResponse])
async def list_egg_losses(
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[EggLossService, Depends(get_egg_loss_service)],
    product_id: Annotated[UUID | None, Query()] = None,
    reason: Annotated[EggLossReason | None, Query()] = None,
    from_date: Annotated[date | None, Query()] = None,
    to_date: Annotated[date | None, Query()] = None,
) -> list[EggLossResponse]:
    return await service.list_losses(
        farm,
        product_id=product_id,
        reason=reason,
        from_date=from_date,
        to_date=to_date,
    )


@router.post("", response_model=EggLossResponse, status_code=status.HTTP_201_CREATED)
async def create_egg_loss(
    request: EggLossCreateRequest,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[EggLossService, Depends(get_egg_loss_service)],
) -> EggLossResponse:
    return await service.create_loss(farm, request)


@router.post(
    "/batch",
    response_model=list[EggLossResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_egg_loss_batch(
    request: EggLossBatchCreateRequest,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[EggLossService, Depends(get_egg_loss_service)],
) -> list[EggLossResponse]:
    return await service.create_batch_loss(farm, request)