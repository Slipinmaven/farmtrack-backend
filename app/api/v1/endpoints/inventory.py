from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.dependencies.farm import get_owned_farm
from app.dependencies.services import (
    get_inventory_purchase_service,
    get_inventory_service,
)
from app.models.farm import Farm
from app.schemas.inventory import (
    InventoryAdjustmentRequest,
    InventoryMovementResponse,
    InventoryOverviewResponse,
    InventoryPurchaseRequest,
)
from app.schemas.transaction import TransactionResponse
from app.services.inventory_service import InventoryService
from app.services.inventory_purchase_service import InventoryPurchaseService


router = APIRouter(prefix="/farms/{farm_id}/inventory", tags=["Inventory"])


@router.get("", response_model=InventoryOverviewResponse)
async def get_inventory(
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[InventoryService, Depends(get_inventory_service)],
    product_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> InventoryOverviewResponse:
    return await service.get_overview(
        farm,
        product_id=product_id,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/opening-balances",
    response_model=InventoryMovementResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_opening_balance(
    request: InventoryAdjustmentRequest,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[InventoryService, Depends(get_inventory_service)],
) -> InventoryMovementResponse:
    return await service.record_opening_balance(farm, request)


@router.post(
    "/adjustments",
    response_model=InventoryMovementResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_inventory_adjustment(
    request: InventoryAdjustmentRequest,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[InventoryService, Depends(get_inventory_service)],
) -> InventoryMovementResponse:
    return await service.record_adjustment(farm, request)


@router.post(
    "/purchases",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_inventory_purchase(
    request: InventoryPurchaseRequest,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[
        InventoryPurchaseService,
        Depends(get_inventory_purchase_service),
    ],
) -> TransactionResponse:
    return await service.create_purchase(
        farm.id,
        request,
        user_id=farm.owner_id,
    )
