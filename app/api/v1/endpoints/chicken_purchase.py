from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.dependencies.farm import get_owned_farm
from app.dependencies.services import (
    get_chicken_purchase_details_service,
    get_chicken_purchase_options_service,
    get_chicken_purchase_service,
)
from app.models.farm import Farm
from app.schemas.chicken_purchase import (
    ChickenPurchaseDetailResponse,
    ChickenPurchaseOptionsResponse,
    ChickenPurchaseRequest,
    ChickenPurchaseResponse,
)
from app.services.chicken_purchase_service import ChickenPurchaseService
from app.services.chicken_purchase_details_service import (
    ChickenPurchaseDetailsService,
)
from app.services.chicken_purchase_options_service import ChickenPurchaseOptionsService

router = APIRouter(
    prefix="/farms/{farm_id}/chicken-purchases",
    tags=["Chicken Purchases"],
)


@router.get("/options", response_model=ChickenPurchaseOptionsResponse)
async def get_chicken_purchase_options(
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[
        ChickenPurchaseOptionsService,
        Depends(get_chicken_purchase_options_service),
    ],
) -> ChickenPurchaseOptionsResponse:
    return await service.get_options(farm)


@router.get("/{transaction_id}", response_model=ChickenPurchaseDetailResponse)
async def get_chicken_purchase_details(
    transaction_id: UUID,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[
        ChickenPurchaseDetailsService,
        Depends(get_chicken_purchase_details_service),
    ],
) -> ChickenPurchaseDetailResponse:
    return await service.get_details(farm.id, transaction_id)


@router.post("", response_model=ChickenPurchaseResponse, status_code=status.HTTP_201_CREATED)
async def create_chicken_purchase(
    request: ChickenPurchaseRequest,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[ChickenPurchaseService, Depends(get_chicken_purchase_service)],
) -> ChickenPurchaseResponse:
    return await service.create_chicken_purchase(
        farm.id,
        request,
        user_id=farm.owner_id,
    )
