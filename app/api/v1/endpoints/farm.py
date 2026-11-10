from __future__ import annotations

import asyncio
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi import File, UploadFile

from typing import Annotated
from app.dependencies.auth import get_current_user
from app.dependencies.farm import get_farm_manager, get_farm_owner
from app.presentation.dependencies.services import get_farm_membership_service, get_farm_service
from app.schemas.farm import (
    FarmCreateRequest,
    FarmResponse,
    FarmSettingsResponse,
    FarmSettingsUpdate,
    FarmUpdateRequest,
)
from app.schemas.farm_membership import (
    FarmMemberInviteRequest,
    FarmMemberRoleUpdateRequest,
    FarmMembershipResponse,
)
from app.services.farm_service import FarmService
from app.services.farm_membership_service import FarmMembershipService
from app.models.farm_membership import FarmMembership
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


@router.get(
    "/invitations",
    response_model=list[FarmMembershipResponse],
    status_code=status.HTTP_200_OK,
)
async def list_farm_invitations(
    current_user: User = Depends(get_current_user),
    service: FarmMembershipService = Depends(get_farm_membership_service),
) -> list[FarmMembership]:
    return await service.list_invitations(current_user)


@router.post(
    "/invitations/{membership_id}/accept",
    response_model=FarmMembershipResponse,
)
async def accept_farm_invitation(
    membership_id: UUID,
    current_user: User = Depends(get_current_user),
    service: FarmMembershipService = Depends(get_farm_membership_service),
) -> FarmMembership:
    return await service.accept_invitation(
        membership_id=membership_id,
        user=current_user,
    )


@router.get(
    "/{farm_id}/members",
    response_model=list[FarmMembershipResponse],
)
async def list_farm_members(
    farm: Farm = Depends(get_farm_manager),
    service: FarmMembershipService = Depends(get_farm_membership_service),
) -> list[FarmMembership]:
    return await service.list_members(farm)


@router.post(
    "/{farm_id}/members",
    response_model=FarmMembershipResponse,
    status_code=status.HTTP_201_CREATED,
)
async def invite_farm_member(
    request: FarmMemberInviteRequest,
    farm: Farm = Depends(get_farm_manager),
    current_user: User = Depends(get_current_user),
    service: FarmMembershipService = Depends(get_farm_membership_service),
) -> FarmMembership:
    return await service.invite(
        farm=farm,
        actor=current_user,
        email=str(request.email),
        role=request.role,
        create_account=request.create_account,
        initial_password=(
            request.initial_password.get_secret_value()
            if request.initial_password is not None
            else None
        ),
    )


@router.patch(
    "/{farm_id}/members/{membership_id}",
    response_model=FarmMembershipResponse,
)
async def update_farm_member_role(
    membership_id: UUID,
    request: FarmMemberRoleUpdateRequest,
    farm: Farm = Depends(get_farm_manager),
    current_user: User = Depends(get_current_user),
    service: FarmMembershipService = Depends(get_farm_membership_service),
) -> FarmMembership:
    return await service.update_role(
        farm=farm,
        actor=current_user,
        membership_id=membership_id,
        role=request.role,
    )


@router.delete(
    "/{farm_id}/members/{membership_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def revoke_farm_member(
    membership_id: UUID,
    farm: Farm = Depends(get_farm_manager),
    current_user: User = Depends(get_current_user),
    service: FarmMembershipService = Depends(get_farm_membership_service),
) -> Response:
    await service.revoke(
        farm=farm,
        actor=current_user,
        membership_id=membership_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{farm_id}/members/{membership_id}/resend-invitation",
    response_model=FarmMembershipResponse,
)
async def resend_farm_invitation(
    membership_id: UUID,
    farm: Farm = Depends(get_farm_manager),
    current_user: User = Depends(get_current_user),
    service: FarmMembershipService = Depends(get_farm_membership_service),
) -> FarmMembership:
    return await service.resend_invitation(
        farm=farm,
        actor=current_user,
        membership_id=membership_id,
    )


@router.patch("/{farm_id}", response_model=FarmResponse)
async def update_farm(
    request: FarmUpdateRequest,
    farm: Farm = Depends(get_farm_manager),
    service: FarmService = Depends(get_farm_service),
) -> FarmResponse:
    return await service.update_farm(
        farm=farm,
        farm_data=request,
    )


@router.post("/{farm_id}/setup/complete", response_model=FarmResponse)
async def complete_farm_setup(
    farm: Farm = Depends(get_farm_manager),
    service: FarmService = Depends(get_farm_service),
) -> FarmResponse:
    return await service.complete_setup(farm)


@router.patch("/{farm_id}/settings", response_model=FarmSettingsResponse)
async def update_farm_settings(
    request: FarmSettingsUpdate,
    farm: Farm = Depends(get_farm_manager),
    service: FarmService = Depends(get_farm_service),
) -> FarmSettingsResponse:
    return await service.update_farm_settings(
        farm=farm,
        settings_data=request,
    )


@router.post("/{farm_id}/logo", response_model=FarmSettingsResponse)
async def upload_farm_logo(
    file: Annotated[UploadFile, File(description="PNG, JPEG, or WebP logo")],
    farm: Farm = Depends(get_farm_manager),
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
    farm: Farm = Depends(get_farm_manager),
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
    farm: Farm = Depends(get_farm_owner),
    service: FarmService = Depends(get_farm_service),
) -> Response:
    await service.delete_farm(farm=farm)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
