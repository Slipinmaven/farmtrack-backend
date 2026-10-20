from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.dependencies.farm import get_owned_farm
from app.dependencies.services import get_purchase_return_service
from app.models.farm import Farm
from app.schemas.purchase_return import (
    PurchaseReturnCreateRequest,
    PurchaseReturnHistoryResponse,
    PurchaseReturnResponse,
)
from app.services.purchase_return_service import PurchaseReturnService

router = APIRouter(
    prefix="/farms/{farm_id}/purchases/{transaction_id}/returns",
    tags=["Purchase Returns"],
)


@router.post("", response_model=PurchaseReturnResponse, status_code=status.HTTP_201_CREATED)
async def create_purchase_return(
    transaction_id: UUID,
    request: PurchaseReturnCreateRequest,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[PurchaseReturnService, Depends(get_purchase_return_service)],
) -> PurchaseReturnResponse:
    return await service.create_return(
        farm.id,
        transaction_id,
        request,
        user_id=farm.owner_id,
    )


@router.get("", response_model=list[PurchaseReturnHistoryResponse])
async def list_purchase_returns(
    transaction_id: UUID,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[PurchaseReturnService, Depends(get_purchase_return_service)],
) -> list[PurchaseReturnHistoryResponse]:
    return await service.list_returns(farm.id, transaction_id)