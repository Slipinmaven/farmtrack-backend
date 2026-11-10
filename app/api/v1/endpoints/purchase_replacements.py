from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.dependencies.farm import get_owned_farm
from app.presentation.dependencies.services import get_purchase_replacement_service
from app.models.farm import Farm
from app.schemas.purchase_replacement import (
    PurchaseReplacementCreateRequest,
    PurchaseReplacementHistoryResponse,
    PurchaseReplacementResponse,
)
from app.services.purchase_replacement_service import PurchaseReplacementService

router = APIRouter(
    prefix="/farms/{farm_id}/purchases/{transaction_id}/replacements",
    tags=["Purchase Replacements"],
)


@router.post("", response_model=PurchaseReplacementResponse, status_code=status.HTTP_201_CREATED)
async def create_purchase_replacement(
    transaction_id: UUID,
    request: PurchaseReplacementCreateRequest,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[
        PurchaseReplacementService,
        Depends(get_purchase_replacement_service),
    ],
) -> PurchaseReplacementResponse:
    return await service.create_replacement(
        farm.id,
        transaction_id,
        request,
        user_id=farm.owner_id,
    )


@router.get("", response_model=list[PurchaseReplacementHistoryResponse])
async def list_purchase_replacements(
    transaction_id: UUID,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[
        PurchaseReplacementService,
        Depends(get_purchase_replacement_service),
    ],
) -> list[PurchaseReplacementHistoryResponse]:
    return await service.list_replacements(farm.id, transaction_id)