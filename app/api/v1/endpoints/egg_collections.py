from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.dependencies.farm import get_owned_farm
from app.dependencies.services import (
    get_egg_collection_options_service,
    get_egg_collection_service,
)
from app.models.farm import Farm
from app.schemas.egg_collection import (
    EggCollectionCreateRequest,
    EggCollectionOptionsResponse,
    EggCollectionResponse,
)
from app.services.egg_collection_options_service import EggCollectionOptionsService
from app.services.egg_collection_service import EggCollectionService

router = APIRouter(
    prefix="/farms/{farm_id}/egg-collections",
    tags=["Egg Collections"],
)


@router.get("/options", response_model=EggCollectionOptionsResponse)
async def get_egg_collection_options(
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[
        EggCollectionOptionsService,
        Depends(get_egg_collection_options_service),
    ],
) -> EggCollectionOptionsResponse:
    return await service.get_options(farm)


@router.get("", response_model=list[EggCollectionResponse])
async def list_egg_collections(
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[EggCollectionService, Depends(get_egg_collection_service)],
    product_id: Annotated[UUID | None, Query()] = None,
    block_id: Annotated[UUID | None, Query()] = None,
    from_datetime: Annotated[datetime | None, Query()] = None,
    to_datetime: Annotated[datetime | None, Query()] = None,
) -> list[EggCollectionResponse]:
    return await service.list_collections(
        farm,
        product_id=product_id,
        block_id=block_id,
        from_datetime=from_datetime,
        to_datetime=to_datetime,
    )


@router.post(
    "",
    response_model=list[EggCollectionResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_egg_collection(
    request: EggCollectionCreateRequest,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[EggCollectionService, Depends(get_egg_collection_service)],
) -> list[EggCollectionResponse]:
    return await service.create_collections(farm, request)