from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.dependencies.farm import get_owned_farm
from app.presentation.dependencies.services import get_purchase_receipt_service
from app.models.farm import Farm
from app.schemas.chicken_purchase import (
    PurchaseReceiptCreateRequest,
    PurchaseReceiptResponse,
)
from app.services.purchase_receipt_service import PurchaseReceiptService

router = APIRouter(
    prefix="/farms/{farm_id}/purchase-receipts",
    tags=["Purchase Receipts"],
)


@router.get("", response_model=list[PurchaseReceiptResponse])
async def list_purchase_receipts(
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[PurchaseReceiptService, Depends(get_purchase_receipt_service)],
) -> list[PurchaseReceiptResponse]:
    return await service.list_receipts(farm.id)


@router.get("/{receipt_id}", response_model=PurchaseReceiptResponse)
async def get_purchase_receipt(
    receipt_id: UUID,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[PurchaseReceiptService, Depends(get_purchase_receipt_service)],
) -> PurchaseReceiptResponse:
    return await service.get_receipt(farm.id, receipt_id)


@router.post("", response_model=PurchaseReceiptResponse, status_code=status.HTTP_201_CREATED)
async def create_purchase_receipt(
    request: PurchaseReceiptCreateRequest,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[PurchaseReceiptService, Depends(get_purchase_receipt_service)],
) -> PurchaseReceiptResponse:
    return await service.create_receipt(
        farm.id,
        request,
        user_id=farm.owner_id,
    )