from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.dependencies.farm import get_owned_farm
from app.dependencies.services import get_transaction_settlement_service
from app.models.farm import Farm
from app.schemas.transaction_settlement import (
    TransactionSettlementBalanceResponse,
    TransactionSettlementCreateRequest,
    TransactionSettlementResponse,
)
from app.services.transaction_settlement_service import TransactionSettlementService

router = APIRouter(
    prefix="/farms/{farm_id}/transactions/{transaction_id}/settlements",
    tags=["Transaction Settlements"],
)


@router.get("", response_model=list[TransactionSettlementResponse])
async def list_transaction_settlements(
    transaction_id: UUID,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[
        TransactionSettlementService,
        Depends(get_transaction_settlement_service),
    ],
) -> list[TransactionSettlementResponse]:
    return await service.list_for_transaction(farm, transaction_id)


@router.post(
    "",
    response_model=TransactionSettlementBalanceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_transaction_settlement(
    transaction_id: UUID,
    request: TransactionSettlementCreateRequest,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[
        TransactionSettlementService,
        Depends(get_transaction_settlement_service),
    ],
) -> TransactionSettlementBalanceResponse:
    return await service.create(farm, transaction_id, request)
