from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.dependencies.farm import get_owned_farm
from app.presentation.dependencies.services import get_transaction_service
from app.models.farm import Farm
from app.schemas.payment import PaymentCreate, PaymentRecordResponse
from app.services.transaction_service import TransactionService

router = APIRouter(
    prefix="/farms/{farm_id}/transactions/{transaction_id}/payments",
    tags=["Transaction Payments"],
)


@router.post("", response_model=PaymentRecordResponse, status_code=status.HTTP_201_CREATED)
async def record_transaction_payment(
    transaction_id: UUID,
    request: PaymentCreate,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[TransactionService, Depends(get_transaction_service)],
) -> PaymentRecordResponse:
    return await service.record_payment(
        farm.id,
        transaction_id,
        request,
        user_id=farm.owner_id,
    )
