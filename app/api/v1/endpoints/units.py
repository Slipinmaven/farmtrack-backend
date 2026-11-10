from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.dependencies.auth import get_current_user
from app.presentation.dependencies.services import get_unit_service
from app.models.user import User
from app.schemas.unit import UnitCreateRequest, UnitResponse, UnitUpdateRequest
from app.services.unit_service import UnitService


router = APIRouter(
    prefix="/units",
    tags=["Units"],
)


@router.get("", response_model=list[UnitResponse])
async def list_units(
    current_user: User = Depends(get_current_user),
    service: UnitService = Depends(get_unit_service),
    search: Annotated[str | None, Query()] = None,
) -> list[UnitResponse]:
    return await service.list_units(current_user, search=search)


@router.post("", response_model=UnitResponse, status_code=status.HTTP_201_CREATED)
async def create_unit(
    request: UnitCreateRequest,
    current_user: User = Depends(get_current_user),
    service: UnitService = Depends(get_unit_service),
) -> UnitResponse:
    return await service.create_unit(current_user, request)


@router.get("/{unit_id}", response_model=UnitResponse)
async def get_unit(
    unit_id: UUID,
    current_user: User = Depends(get_current_user),
    service: UnitService = Depends(get_unit_service),
) -> UnitResponse:
    return await service.get_unit(current_user, unit_id)


@router.patch("/{unit_id}", response_model=UnitResponse)
async def update_unit(
    unit_id: UUID,
    request: UnitUpdateRequest,
    current_user: User = Depends(get_current_user),
    service: UnitService = Depends(get_unit_service),
) -> UnitResponse:
    return await service.update_unit(current_user, unit_id, request)


@router.delete(
    "/{unit_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_unit(
    unit_id: UUID,
    current_user: User = Depends(get_current_user),
    service: UnitService = Depends(get_unit_service),
) -> Response:
    await service.delete_unit(current_user, unit_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)