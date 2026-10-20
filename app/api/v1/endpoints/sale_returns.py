from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.dependencies.farm import get_owned_farm
from app.dependencies.services import get_sale_return_service
from app.models.farm import Farm
from app.schemas.sale_return import (
    SaleReturnCreateRequest,
    SaleReturnHistoryResponse,
    SaleReturnResponse,
)
from app.services.sale_return_service import SaleReturnService

router = APIRouter(
    prefix="/farms/{farm_id}/sales/{transaction_id}/returns",
    tags=["Sale Returns"],
)


@router.post("", response_model=SaleReturnResponse, status_code=status.HTTP_201_CREATED)
async def create_sale_return(
    transaction_id: UUID,
    request: SaleReturnCreateRequest,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[SaleReturnService, Depends(get_sale_return_service)],
) -> SaleReturnResponse:
    return await service.create_return(
        farm.id,
        transaction_id,
        request,
        user_id=farm.owner_id,
    )


@router.get("", response_model=list[SaleReturnHistoryResponse])
async def list_sale_returns(
    transaction_id: UUID,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[SaleReturnService, Depends(get_sale_return_service)],
) -> list[SaleReturnHistoryResponse]:
    return await service.list_returns(farm.id, transaction_id)