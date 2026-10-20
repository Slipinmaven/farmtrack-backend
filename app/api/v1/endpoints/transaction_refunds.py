from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.dependencies.farm import get_owned_farm
from app.dependencies.services import get_transaction_refund_service
from app.models.farm import Farm
from app.schemas.transaction_refund import (
    TransactionRefundCreateRequest,
    TransactionRefundRecordResponse,
    TransactionRefundResponse,
)
from app.services.transaction_refund_service import TransactionRefundService

router = APIRouter(
    prefix="/farms/{farm_id}/transactions/{transaction_id}/refunds",
    tags=["Transaction Refunds"],
)


@router.post(
    "",
    response_model=TransactionRefundRecordResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_transaction_refund(
    transaction_id: UUID,
    request: TransactionRefundCreateRequest,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[
        TransactionRefundService,
        Depends(get_transaction_refund_service),
    ],
) -> TransactionRefundRecordResponse:
    return await service.create_refund(
        farm.id,
        transaction_id,
        request,
        user_id=farm.owner_id,
    )


@router.get("", response_model=list[TransactionRefundResponse])
async def list_transaction_refunds(
    transaction_id: UUID,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[
        TransactionRefundService,
        Depends(get_transaction_refund_service),
    ],
) -> list[TransactionRefundResponse]:
    return await service.list_refunds(farm.id, transaction_id)