from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.dependencies.farm import get_owned_farm
from app.presentation.dependencies.services import get_sale_delivery_service
from app.models.farm import Farm
from app.schemas.sale_delivery import (
    SaleDeliveryCreateRequest,
    SaleDeliveryResponse,
    SaleFulfillmentResponse,
)
from app.services.sale_delivery_service import SaleDeliveryService

router = APIRouter(
    prefix="/farms/{farm_id}/sales",
    tags=["Sale Deliveries"],
)


@router.post(
    "/{transaction_id}/deliveries",
    response_model=SaleDeliveryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_sale_delivery(
    transaction_id: UUID,
    request: SaleDeliveryCreateRequest,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[
        SaleDeliveryService,
        Depends(get_sale_delivery_service),
    ],
) -> SaleDeliveryResponse:
    return await service.create_delivery(
        farm.id,
        transaction_id,
        request,
        user_id=farm.owner_id,
    )


@router.get(
    "/{transaction_id}/fulfillment",
    response_model=SaleFulfillmentResponse,
)
async def get_sale_fulfillment(
    transaction_id: UUID,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[
        SaleDeliveryService,
        Depends(get_sale_delivery_service),
    ],
) -> SaleFulfillmentResponse:
    return await service.get_fulfillment(farm.id, transaction_id)


@router.get(
    "/{transaction_id}/deliveries",
    response_model=list[SaleDeliveryResponse],
)
async def list_sale_deliveries(
    transaction_id: UUID,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[
        SaleDeliveryService,
        Depends(get_sale_delivery_service),
    ],
) -> list[SaleDeliveryResponse]:
    return await service.list_deliveries(farm.id, transaction_id)
