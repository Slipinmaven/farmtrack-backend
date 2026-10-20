from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.dependencies.farm import get_owned_farm
from app.dependencies.services import (
    get_chicken_sale_details_service,
    get_chicken_sale_options_service,
    get_chicken_sale_service,
)
from app.models.farm import Farm
from app.schemas.chicken_sale import (
    ChickenSaleOptionsResponse,
    ChickenSaleDetailResponse,
    ChickenSaleRequest,
    ChickenSaleResponse,
)
from app.schemas.transaction import TransactionResponse
from app.schemas.transaction_settlement import ChickenSettlementOptionsResponse
from app.services.chicken_sale_options_service import ChickenSaleOptionsService
from app.services.chicken_sale_details_service import ChickenSaleDetailsService
from app.services.chicken_sale_service import ChickenSaleService

router = APIRouter(
    prefix="/farms/{farm_id}/chicken-sales",
    tags=["Chicken Sales"],
)

@router.get(
    "/settlement-options",
    response_model=ChickenSettlementOptionsResponse,
)
async def get_chicken_settlement_options(
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[
        ChickenSaleOptionsService,
        Depends(get_chicken_sale_options_service),
    ],
    selection: Literal[
        "receive_batch",
        "issue_batch",
        "receive_block",
        "issue_block",
    ],
    search: Annotated[str | None, Query(max_length=100)] = None,
    batch_id: UUID | None = None,
    block_id: UUID | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ChickenSettlementOptionsResponse:
    return await service.get_settlement_options(
        farm,
        selection=selection,
        search=search,
        batch_id=batch_id,
        block_id=block_id,
        offset=offset,
    )


@router.get("/options", response_model=ChickenSaleOptionsResponse)
async def get_chicken_sale_options(
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[
        ChickenSaleOptionsService,
        Depends(get_chicken_sale_options_service),
    ],
) -> ChickenSaleOptionsResponse:
    return await service.get_options(farm)


@router.get("/{transaction_id}", response_model=ChickenSaleDetailResponse)
async def get_chicken_sale_details(
    transaction_id: UUID,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[
        ChickenSaleDetailsService,
        Depends(get_chicken_sale_details_service),
    ],
) -> ChickenSaleDetailResponse:
    return await service.get_details(farm.id, transaction_id)


@router.post("", response_model=ChickenSaleResponse, status_code=status.HTTP_201_CREATED)
async def create_chicken_sale(
    request: ChickenSaleRequest,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[ChickenSaleService, Depends(get_chicken_sale_service)],
) -> ChickenSaleResponse:
    transaction: TransactionResponse = await service.create_chicken_sale(
        farm.id,
        request,
        user_id=farm.owner_id,
    )
    return ChickenSaleResponse.model_validate(transaction, from_attributes=True)
