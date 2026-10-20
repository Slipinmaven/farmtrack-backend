from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi import File, UploadFile

from typing import Annotated
from app.dependencies.auth import get_current_user
from app.dependencies.farm import get_owned_farm
from app.dependencies.services import get_farm_service
from app.schemas.farm import (
    FarmCreateRequest,
    FarmResponse,
    FarmSettingsResponse,
    FarmSettingsUpdate,
    FarmUpdateRequest,
)
from app.services.farm_service import FarmService
from app.models.user import User
from app.models.farm import Farm
from app.services.farm_logo_storage import (
    MAX_FARM_LOGO_BYTES,
    FarmLogoStorage,
)

router = APIRouter(
    prefix="/farms",
    tags=["Farms"],
)
logo_storage = FarmLogoStorage()

@router.get("", response_model=list[FarmResponse], status_code=status.HTTP_200_OK)
async def list_farms(
    current_user: User = Depends(get_current_user),
    service: FarmService = Depends(get_farm_service),
    search: Annotated[str | None,Query()] = None,
    is_active: Annotated[bool | None,Query()] = None,
    ) -> list[FarmResponse]:
    
    farms = await service.get_user_farms(current_user, search=search, is_active=is_active)
    return [FarmResponse.model_validate(farm) for farm in farms]

@router.post(
    "/create",
    response_model=FarmResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_farm(
    request: FarmCreateRequest,
    current_user: User = Depends(get_current_user),
    service: FarmService = Depends(get_farm_service),
 ) -> FarmResponse:
    return await service.create_farm(user=current_user, farm_data=request)


@router.patch("/{farm_id}", response_model=FarmResponse)
async def update_farm(
    request: FarmUpdateRequest,
    farm: Farm = Depends(get_owned_farm),
    service: FarmService = Depends(get_farm_service),
) -> FarmResponse:
    return await service.update_farm(
        farm=farm,
        farm_data=request,
    )


@router.post("/{farm_id}/setup/complete", response_model=FarmResponse)
async def complete_farm_setup(
    farm: Farm = Depends(get_owned_farm),
    service: FarmService = Depends(get_farm_service),
) -> FarmResponse:
    return await service.complete_setup(farm)


@router.patch("/{farm_id}/settings", response_model=FarmSettingsResponse)
async def update_farm_settings(
    request: FarmSettingsUpdate,
    farm: Farm = Depends(get_owned_farm),
    service: FarmService = Depends(get_farm_service),
) -> FarmSettingsResponse:
    return await service.update_farm_settings(
        farm=farm,
        settings_data=request,
    )


@router.post("/{farm_id}/logo", response_model=FarmSettingsResponse)
async def upload_farm_logo(
    file: Annotated[UploadFile, File(description="PNG, JPEG, or WebP logo")],
    farm: Farm = Depends(get_owned_farm),
    service: FarmService = Depends(get_farm_service),
) -> FarmSettingsResponse:
    previous = await service.get_farm_with_settings(farm)
    try:
        content = await file.read(MAX_FARM_LOGO_BYTES + 1)
    finally:
        await file.close()

    logo_path = await asyncio.to_thread(
        logo_storage.save,
        farm.id,
        file.content_type,
        content,
    )
    try:
        updated_settings = await service.update_farm_settings(
            farm=farm,
            settings_data=FarmSettingsUpdate(logo_path=logo_path),
        )
    except Exception:
        await asyncio.to_thread(logo_storage.delete, logo_path)
        raise

    if previous.settings is not None:
        await asyncio.to_thread(logo_storage.delete, previous.settings.logo_path)
    return updated_settings


@router.delete("/{farm_id}/logo", response_model=FarmSettingsResponse)
async def delete_farm_logo(
    farm: Farm = Depends(get_owned_farm),
    service: FarmService = Depends(get_farm_service),
) -> FarmSettingsResponse:
    previous = await service.get_farm_with_settings(farm)
    updated_settings = await service.update_farm_settings(
        farm=farm,
        settings_data=FarmSettingsUpdate(logo_path=None),
    )
    if previous.settings is not None:
        await asyncio.to_thread(logo_storage.delete, previous.settings.logo_path)
    return updated_settings


@router.delete(
    "/{farm_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_farm(
    farm: Farm = Depends(get_owned_farm),
    service: FarmService = Depends(get_farm_service),
) -> Response:
    await service.delete_farm(farm=farm)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
