from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.dependencies.farm import get_owned_farm
from app.presentation.dependencies.services import get_purchase_supplier_refund_service
from app.models.farm import Farm
from app.schemas.purchase_supplier_refund import (
    PurchaseSupplierRefundCreateRequest,
    PurchaseSupplierRefundRecordResponse,
    PurchaseSupplierRefundResponse,
)
from app.services.purchase_supplier_refund_service import PurchaseSupplierRefundService

router = APIRouter(
    prefix="/farms/{farm_id}/transactions/{transaction_id}/supplier-refunds",
    tags=["Supplier Refunds"],
)


@router.post(
    "",
    response_model=PurchaseSupplierRefundRecordResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_supplier_refund(
    transaction_id: UUID,
    request: PurchaseSupplierRefundCreateRequest,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[
        PurchaseSupplierRefundService,
        Depends(get_purchase_supplier_refund_service),
    ],
) -> PurchaseSupplierRefundRecordResponse:
    return await service.create_refund(
        farm.id,
        transaction_id,
        request,
        user_id=farm.owner_id,
    )


@router.get("", response_model=list[PurchaseSupplierRefundResponse])
async def list_supplier_refunds(
    transaction_id: UUID,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[
        PurchaseSupplierRefundService,
        Depends(get_purchase_supplier_refund_service),
    ],
) -> list[PurchaseSupplierRefundResponse]:
    return await service.list_refunds(farm.id, transaction_id)