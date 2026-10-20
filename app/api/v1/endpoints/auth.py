from uuid import UUID

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.dependencies.auth import get_current_user
from app.dependencies.services import get_auth_service
from app.dependencies.services import get_activity_service
from app.models.user import User
from app.schemas.auth import (
    AuthenticationResponse,
    BlockedDeviceResponse,
    DeviceBlockRequest,
    LoginRequest,
    PasswordChangeRequest,
    RefreshRequest,
    SessionHistoryResponse,
    UserResponse,
)
from app.schemas.activity import ActivityFeedResponse
from app.services.activity_service import ActivityService
from app.services.auth_service import AuthService

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)

@router.post("/login", response_model=AuthenticationResponse, status_code=status.HTTP_200_OK)
async def login(
    request: LoginRequest, 
    http_request: Request,
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthenticationResponse:
    ip_address = http_request.client.host if http_request.client else None
    return await auth_service.login_user(
        email=request.email, 
        password=request.password,
        device_id=request.device_id,
        device_name=request.device_name,
        platform=request.platform,
        ip_address=ip_address,
        user_agent=http_request.headers.get("user-agent"),
    )


@router.post("/refresh", response_model=AuthenticationResponse)
async def refresh(
    request: RefreshRequest,
    http_request: Request,
    service: AuthService = Depends(get_auth_service),
) -> AuthenticationResponse:
    return await service.refresh(
        request.refresh_token,
        device_id=request.device_id,
        device_name=request.device_name,
        platform=request.platform,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
    )

@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: RefreshRequest,
    service: AuthService = Depends(get_auth_service),
) -> None:
    await service.logout(request.refresh_token.get_secret_value())


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    request: PasswordChangeRequest,
    http_request: Request,
    current_user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
) -> None:
    await service.change_password(
        current_user.id,
        http_request.state.auth_session_id,
        request.current_password,
        request.new_password,
    )


@router.get("/sessions", response_model=SessionHistoryResponse)
async def list_sessions(
    http_request: Request,
    limit: int = Query(default=5, ge=1, le=30),
    offset: int = Query(default=0, ge=0),
    session_status: Literal["all", "active", "ended"] = Query(
        default="all",
        alias="status",
    ),
    search: str | None = Query(default=None, max_length=100),
    current_user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
) -> SessionHistoryResponse:
    return await service.list_sessions(
        current_user.id,
        http_request.state.auth_session_id,
        limit=limit,
        offset=offset,
        status=session_status,
        search=search,
    )


@router.post("/sessions/{session_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
) -> None:
    await service.revoke_session(current_user.id, session_id)


@router.post(
    "/sessions/{session_id}/block",
    response_model=BlockedDeviceResponse,
    status_code=status.HTTP_200_OK,
)
async def block_session_device(
    session_id: UUID,
    request: DeviceBlockRequest,
    current_user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
) -> BlockedDeviceResponse:
    return await service.block_session_device(
        current_user.id,
        session_id,
        request.permanent,
        request.duration_days,
    )


@router.delete(
    "/blocked-devices/{block_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unblock_device(
    block_id: UUID,
    current_user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
) -> None:
    await service.unblock_device(current_user.id, block_id)


@router.get(
    "/sessions/{session_id}/activities",
    response_model=ActivityFeedResponse,
)
async def list_session_activities(
    session_id: UUID,
    limit: int = Query(default=20, ge=1, le=50),
    before: str | None = Query(default=None, max_length=256),
    current_user: User = Depends(get_current_user),
    service: ActivityService = Depends(get_activity_service),
) -> ActivityFeedResponse:
    return await service.list_for_session(
        user_id=current_user.id,
        session_id=session_id,
        limit=limit,
        before=before,
    )

