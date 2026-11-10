from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.dependencies.farm import get_owned_farm
from app.presentation.dependencies.services import get_inventory_opening_setup_service
from app.models.farm import Farm
from app.schemas.inventory_opening_setup import (
    InventoryOpeningSetupRequest,
    InventoryOpeningSetupResponse,
    InventoryOpeningSetupStatusResponse,
)
from app.services.inventory_opening_setup_service import (
    InventoryOpeningSetupService,
)

router = APIRouter(
    prefix="/farms/{farm_id}/inventory/opening-stock",
    tags=["Inventory"],
)


@router.get("", response_model=InventoryOpeningSetupStatusResponse)
async def get_opening_stock_status(
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[
        InventoryOpeningSetupService,
        Depends(get_inventory_opening_setup_service),
    ],
) -> InventoryOpeningSetupStatusResponse:
    return await service.get_status(farm)


@router.post(
    "",
    response_model=InventoryOpeningSetupResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_opening_stock(
    request: InventoryOpeningSetupRequest,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[
        InventoryOpeningSetupService,
        Depends(get_inventory_opening_setup_service),
    ],
) -> InventoryOpeningSetupResponse:
    return await service.create(farm, request)
