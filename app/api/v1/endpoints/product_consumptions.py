from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.dependencies.farm import get_owned_farm
from app.presentation.dependencies.services import get_product_consumption_service
from app.models.farm import Farm
from app.schemas.product_consumption import (
    ProductConsumptionBatchCreateRequest,
    ProductConsumptionCreateRequest,
    ProductConsumptionResponse,
)
from app.services.product_consumption_service import ProductConsumptionService

router = APIRouter(
    prefix="/farms/{farm_id}/product-consumptions",
    tags=["Product Consumptions"],
)


@router.get("", response_model=list[ProductConsumptionResponse])
async def list_product_consumptions(
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[
        ProductConsumptionService,
        Depends(get_product_consumption_service),
    ],
    product_id: Annotated[UUID | None, Query()] = None,
    block_id: Annotated[UUID | None, Query()] = None,
    batch_id: Annotated[UUID | None, Query()] = None,
    from_date: Annotated[date | None, Query()] = None,
    to_date: Annotated[date | None, Query()] = None,
) -> list[ProductConsumptionResponse]:
    return await service.list_consumptions(
        farm,
        product_id=product_id,
        block_id=block_id,
        batch_id=batch_id,
        from_date=from_date,
        to_date=to_date,
    )


@router.post(
    "",
    response_model=ProductConsumptionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_product_consumption(
    request: ProductConsumptionCreateRequest,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[
        ProductConsumptionService,
        Depends(get_product_consumption_service),
    ],
) -> ProductConsumptionResponse:
    return await service.record_consumption(farm, request)


@router.post(
    "/batch",
    response_model=list[ProductConsumptionResponse],
    status_code=status.HTTP_201_CREATED,
)
async def record_product_consumption_batch(
    request: ProductConsumptionBatchCreateRequest,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[
        ProductConsumptionService,
        Depends(get_product_consumption_service),
    ],
) -> list[ProductConsumptionResponse]:
    return await service.record_consumptions(farm, request)