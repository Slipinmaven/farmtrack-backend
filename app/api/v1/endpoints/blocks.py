from uuid import UUID

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.dependencies.farm import get_owned_farm
from app.presentation.dependencies.services import get_block_service
from app.models.farm import Farm
from app.schemas.block import (
    BlockCreateRequest,
    BlockDetailResponse,
    BlockResponse,
    BlockUpdateRequest,
)
from app.services.block_service import BlockService


router = APIRouter(
    prefix="/farms/{farm_id}/blocks",
    tags=["Blocks"],
)


@router.get("", response_model=list[BlockResponse])
async def list_blocks(
    farm: Farm = Depends(get_owned_farm),
    service: BlockService = Depends(get_block_service),
    search: Annotated[str | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = None,
    limit: Annotated[int | None, Query(ge=1, le=100)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[BlockResponse]:
    return await service.list_blocks(
        farm,
        search=search,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=BlockResponse, status_code=status.HTTP_201_CREATED)
async def create_block(
    request: BlockCreateRequest,
    farm: Farm = Depends(get_owned_farm),
    service: BlockService = Depends(get_block_service),
) -> BlockResponse:
    return await service.create_block(farm, request)


@router.get("/{block_id}", response_model=BlockDetailResponse)
async def get_block(
    block_id: UUID,
    farm: Farm = Depends(get_owned_farm),
    service: BlockService = Depends(get_block_service),
) -> BlockDetailResponse:
    return await service.get_block(farm, block_id)


@router.patch("/{block_id}", response_model=BlockResponse)
async def update_block(
    block_id: UUID,
    request: BlockUpdateRequest,
    farm: Farm = Depends(get_owned_farm),
    service: BlockService = Depends(get_block_service),
) -> BlockResponse:
    return await service.update_block(farm, block_id, request)


@router.delete(
    "/{block_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_block(
    block_id: UUID,
    farm: Farm = Depends(get_owned_farm),
    service: BlockService = Depends(get_block_service),
) -> Response:
    await service.delete_block(farm, block_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)