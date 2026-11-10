from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.dependencies.farm import get_owned_farm
from app.presentation.dependencies.services import get_chicken_movement_service
from app.models.farm import Farm
from app.schemas.chicken_movement import (
    ChickenMovementBatchCreateRequest,
    ChickenMovementCreateRequest,
    ChickenMovementHistoryResponse,
    ChickenMovementResponse,
    MovementDirection,
)
from app.services.chicken_movement_service import ChickenMovementService

router = APIRouter(
    prefix="/farms/{farm_id}/chicken-movements",
    tags=["Chicken Movements"],
)


@router.get(
    "/blocks/{block_id}",
    response_model=ChickenMovementHistoryResponse,
)
async def list_block_chicken_movement_history(
    block_id: UUID,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[
        ChickenMovementService,
        Depends(get_chicken_movement_service),
    ],
    direction: Annotated[MovementDirection, Query()] = "all",
    search: Annotated[str | None, Query(max_length=100)] = None,
    from_date: Annotated[date | None, Query()] = None,
    to_date: Annotated[date | None, Query()] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ChickenMovementHistoryResponse:
    return await service.list_block_history(
        farm,
        block_id,
        direction=direction,
        search=search,
        from_date=from_date,
        to_date=to_date,
        offset=offset,
        limit=limit,
    )


@router.get("", response_model=list[ChickenMovementResponse])
async def list_chicken_movements(
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[
        ChickenMovementService,
        Depends(get_chicken_movement_service),
    ],
    batch_id: Annotated[UUID | None, Query()] = None,
    from_block_id: Annotated[UUID | None, Query()] = None,
    to_block_id: Annotated[UUID | None, Query()] = None,
    from_date: Annotated[date | None, Query()] = None,
    to_date: Annotated[date | None, Query()] = None,
) -> list[ChickenMovementResponse]:
    return await service.list_movements(
        farm,
        batch_id=batch_id,
        from_block_id=from_block_id,
        to_block_id=to_block_id,
        from_date=from_date,
        to_date=to_date,
    )


@router.post(
    "",
    response_model=ChickenMovementResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_chicken_movement(
    request: ChickenMovementCreateRequest,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[
        ChickenMovementService,
        Depends(get_chicken_movement_service),
    ],
) -> ChickenMovementResponse:
    return await service.create_movement(farm, request)


@router.post(
    "/batch",
    response_model=list[ChickenMovementResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_chicken_batch_movement(
    request: ChickenMovementBatchCreateRequest,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[
        ChickenMovementService,
        Depends(get_chicken_movement_service),
    ],
) -> list[ChickenMovementResponse]:
    return await service.create_batch_movement(farm, request)