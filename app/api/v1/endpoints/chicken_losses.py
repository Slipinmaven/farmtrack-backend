from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.dependencies.farm import get_owned_farm
from app.dependencies.services import get_chicken_loss_service
from app.models.farm import Farm
from app.schemas.chicken_loss import ChickenLossCreateRequest, ChickenLossResponse
from app.schemas.enums import ChickenLossReason
from app.services.chicken_loss_service import ChickenLossService

router = APIRouter(
    prefix="/farms/{farm_id}/chicken-losses",
    tags=["Chicken Losses"],
)


@router.get("", response_model=list[ChickenLossResponse])
async def list_chicken_losses(
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[ChickenLossService, Depends(get_chicken_loss_service)],
    batch_id: Annotated[UUID | None, Query()] = None,
    block_id: Annotated[UUID | None, Query()] = None,
    reason: Annotated[ChickenLossReason | None, Query()] = None,
    from_date: Annotated[date | None, Query()] = None,
    to_date: Annotated[date | None, Query()] = None,
) -> list[ChickenLossResponse]:
    return await service.list_losses(
        farm,
        batch_id=batch_id,
        block_id=block_id,
        reason=reason.value if reason is not None else None,
        from_date=from_date,
        to_date=to_date,
    )


@router.post(
    "",
    response_model=list[ChickenLossResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_chicken_losses(
    request: ChickenLossCreateRequest,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[ChickenLossService, Depends(get_chicken_loss_service)],
) -> list[ChickenLossResponse]:
    return await service.create_losses(farm, request)