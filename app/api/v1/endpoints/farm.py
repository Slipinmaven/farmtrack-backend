from __future__ import annotations

import asyncio
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi import File, UploadFile
from fastapi.responses import FileResponse

from typing import Annotated
from app.dependencies.auth import get_current_user, require_active_account
from app.dependencies.farm import get_farm_manager, get_farm_owner, get_owned_farm
from app.core.exceptions import ResourceNotFoundError
from app.core.logging import get_application_logger
from app.presentation.dependencies.services import get_farm_membership_service, get_farm_service
from app.schemas.farm import (
    FarmDeletionRequest,
    FarmLeaveRequest,
    FarmLeaveResponse,
    PendingFarmDeletionResponse,
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
from app.services.data_deletion_service import (
    DELETION_GRACE_PERIOD,
    DataDeletionService,
)
from app.presentation.dependencies.services import get_data_deletion_service
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
app_logger = get_application_logger()

@router.get("", response_model=list[FarmResponse], status_code=status.HTTP_200_OK)
async def list_farms(
    current_user: User = Depends(require_active_account),
    service: FarmService = Depends(get_farm_service),
    search: Annotated[str | None,Query()] = None,
    is_active: Annotated[bool | None,Query()] = None,
    ) -> list[FarmResponse]:
    
    farms = await service.get_user_farms(current_user, search=search, is_active=is_active)
    responses = [FarmResponse.model_validate(farm) for farm in farms]
    for farm, response in zip(farms, responses):
        if farm.owner_id != current_user.id:
            response.email = None
    return responses


@router.get(
    "/deletion-pending",
    response_model=list[PendingFarmDeletionResponse],
)
async def list_pending_farm_deletions(
    current_user: User = Depends(get_current_user),
    service: DataDeletionService = Depends(get_data_deletion_service),
) -> list[PendingFarmDeletionResponse]:
    farms = await service.list_pending_farm_deletions(current_user.id)
    return [
        PendingFarmDeletionResponse(
            id=farm.id,
            name=farm.name,
            deletion_requested_at=farm.deletion_requested_at,
            scheduled_for=farm.deletion_requested_at + DELETION_GRACE_PERIOD,
        )
        for farm in farms
        if farm.deletion_requested_at is not None
    ]

@router.post(
    "/create",
    response_model=FarmResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_farm(
    request: FarmCreateRequest,
    current_user: User = Depends(require_active_account),
    service: FarmService = Depends(get_farm_service),
 ) -> FarmResponse:
    if (
        request.settings is not None
        and "logo_path" in request.settings.model_fields_set
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Use the farm logo upload endpoint to set a logo.",
        )
    return await service.create_farm(user=current_user, farm_data=request)


@router.get(
    "/invitations",
    response_model=list[FarmMembershipResponse],
    status_code=status.HTTP_200_OK,
)
async def list_farm_invitations(
    current_user: User = Depends(require_active_account),
    service: FarmMembershipService = Depends(get_farm_membership_service),
) -> list[FarmMembership]:
    return await service.list_invitations(current_user)


@router.post(
    "/invitations/{membership_id}/accept",
    response_model=FarmMembershipResponse,
)
async def accept_farm_invitation(
    membership_id: UUID,
    current_user: User = Depends(require_active_account),
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
    current_user: User = Depends(get_current_user),
    service: FarmMembershipService = Depends(get_farm_membership_service),
) -> list[FarmMembershipResponse]:
    memberships = await service.list_members(farm)
    responses = [
        FarmMembershipResponse.model_validate(membership)
        for membership in memberships
    ]
    for membership, response in zip(memberships, responses):
        if membership.user_id == farm.owner_id and current_user.id != farm.owner_id:
            response.email = None
    return responses


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
    if "logo_path" in request.model_fields_set:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Use the farm logo upload or removal endpoint to change a logo.",
        )
    return await service.update_farm_settings(
        farm=farm,
        settings_data=request,
    )


@router.get(
    "/{farm_id}/logo",
    response_class=FileResponse,
    responses={404: {"description": "Farm logo not found."}},
)
async def get_farm_logo(
    farm: Farm = Depends(get_owned_farm),
    service: FarmService = Depends(get_farm_service),
) -> FileResponse:
    logo_path = await service.get_farm_logo_path(farm)
    resolved_logo = await asyncio.to_thread(
        logo_storage.resolve,
        farm.id,
        logo_path,
    )
    if resolved_logo is None:
        raise ResourceNotFoundError("Farm logo not found.")

    path, media_type = resolved_logo
    return FileResponse(
        path,
        media_type=media_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Vary": "Authorization",
        },
    )


@router.post("/{farm_id}/logo", response_model=FarmSettingsResponse)
async def upload_farm_logo(
    file: Annotated[UploadFile, File(description="PNG, JPEG, or WebP logo")],
    farm: Farm = Depends(get_farm_manager),
    service: FarmService = Depends(get_farm_service),
) -> FarmSettingsResponse:
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
        try:
            await asyncio.to_thread(logo_storage.delete, logo_path)
        except OSError:
            try:
                await service.enqueue_farm_logo_cleanup(logo_path)
            except Exception:
                app_logger.exception(
                    "farm_logo_cleanup_enqueue_failed",
                    extra={
                        "event": "farm_logo_cleanup_enqueue_failed",
                        "farm_id": farm.id,
                    },
                )
        raise

    return updated_settings


@router.delete("/{farm_id}/logo", response_model=FarmSettingsResponse)
async def delete_farm_logo(
    farm: Farm = Depends(get_farm_manager),
    service: FarmService = Depends(get_farm_service),
) -> FarmSettingsResponse:
    return await service.update_farm_settings(
        farm=farm,
        settings_data=FarmSettingsUpdate(logo_path=None),
    )


@router.delete(
    "/{farm_id}",
    response_model=PendingFarmDeletionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def delete_farm(
    request: FarmDeletionRequest,
    farm: Farm = Depends(get_farm_owner),
    current_user: User = Depends(get_current_user),
    service: DataDeletionService = Depends(get_data_deletion_service),
) -> PendingFarmDeletionResponse:
    scheduled_for, notification_sent = await service.schedule_farm_deletion(
        farm_id=farm.id,
        owner_id=current_user.id,
        current_password=request.current_password,
    )
    return PendingFarmDeletionResponse(
        id=farm.id,
        name=farm.name,
        deletion_requested_at=scheduled_for - DELETION_GRACE_PERIOD,
        scheduled_for=scheduled_for,
        notification_sent=notification_sent,
    )


@router.post(
    "/{farm_id}/restore",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def restore_farm(
    farm_id: UUID,
    request: FarmDeletionRequest,
    current_user: User = Depends(require_active_account),
    service: DataDeletionService = Depends(get_data_deletion_service),
) -> Response:
    await service.restore_farm(
        farm_id=farm_id,
        owner_id=current_user.id,
        current_password=request.current_password,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{farm_id}/membership",
    response_model=FarmLeaveResponse,
)
async def leave_farm(
    farm_id: UUID,
    request: FarmLeaveRequest,
    current_user: User = Depends(get_current_user),
    service: DataDeletionService = Depends(get_data_deletion_service),
) -> FarmLeaveResponse:
    email_status = await service.leave_farm(
        farm_id=farm_id,
        user_id=current_user.id,
        current_password=request.current_password,
    )
    return FarmLeaveResponse(**email_status)
