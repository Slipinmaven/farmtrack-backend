from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.dependencies.farm import get_owned_farm
from app.presentation.dependencies.services import get_egg_sale_service
from app.models.farm import Farm
from app.schemas.egg_sale import EggSaleCreateRequest
from app.schemas.transaction import TransactionResponse
from app.services.egg_sale_service import EggSaleService

router = APIRouter(
    prefix="/farms/{farm_id}/egg-sales",
    tags=["Egg Sales"],
)


@router.post(
    "",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_egg_sale(
    request: EggSaleCreateRequest,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[EggSaleService, Depends(get_egg_sale_service)],
) -> TransactionResponse:
    return await service.create_sale(farm, request)
