from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.dependencies.farm import get_owned_farm
from app.models.farm import Farm
from app.presentation.dependencies.services import get_receipt_history_service
from app.schemas.receipt_history import (
    ReceiptHistoryFilters,
    ReceiptHistoryResponse,
)
from app.services.receipt_history_service import ReceiptHistoryService

router = APIRouter(prefix="/farms/{farm_id}/receipts", tags=["Receipts"])


@router.get("", response_model=ReceiptHistoryResponse)
async def get_receipt_history(
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[ReceiptHistoryService, Depends(get_receipt_history_service)],
    search: str | None = Query(default=None, max_length=150),
    transaction_type: Literal["all", "sale", "purchase"] = "all",
    receipt_kind: Literal["all", "transaction", "payment"] = "all",
    status: Literal["all", "completed", "cancelled"] = "all",
    from_date: date | None = None,
    to_date: date | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> ReceiptHistoryResponse:
    return await service.get_history(
        farm.id,
        ReceiptHistoryFilters(
            search=search,
            transaction_type=transaction_type,
            receipt_kind=receipt_kind,
            status=status,
            from_date=from_date,
            to_date=to_date,
        ),
        offset,
        limit,
    )
