from uuid import UUID

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import HTMLResponse

from app.dependencies.auth import get_current_user
from app.presentation.dependencies.services import get_auth_service
from app.presentation.dependencies.services import get_activity_service
from app.models.user import User
from app.schemas.auth import (
    AccountDeletionRequest,
    AccountDeletionResponse,
    AccountDeletionStatusResponse,
    AccountRestoreRequest,
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
from app.services.data_deletion_service import DataDeletionService
from app.presentation.dependencies.services import get_data_deletion_service
from app.core.exceptions import ConflictError
from urllib.parse import parse_qs

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


@router.delete(
    "/account",
    response_model=AccountDeletionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def schedule_account_deletion(
    request: AccountDeletionRequest,
    current_user: User = Depends(get_current_user),
    service: DataDeletionService = Depends(get_data_deletion_service),
) -> AccountDeletionResponse:
    scheduled_for, notification_sent = await service.schedule_account_deletion(
        current_user.id,
        request.current_password,
    )
    return AccountDeletionResponse(
        status="scheduled",
        scheduled_for=scheduled_for,
        notification_sent=notification_sent,
    )


@router.get(
    "/account/deletion",
    response_model=AccountDeletionStatusResponse,
)
async def account_deletion_status(
    current_user: User = Depends(get_current_user),
    service: DataDeletionService = Depends(get_data_deletion_service),
) -> AccountDeletionStatusResponse:
    return AccountDeletionStatusResponse.model_validate(
        await service.get_account_deletion_status(current_user.id)
    )


@router.post(
    "/account-deletion/cancel",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def cancel_account_deletion(
    request: AccountRestoreRequest,
    service: DataDeletionService = Depends(get_data_deletion_service),
) -> Response:
    await service.restore_account(
        email=str(request.email),
        password=request.password,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/account-deletion/confirm",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def account_deletion_confirmation_page() -> HTMLResponse:
    return _deletion_confirmation_page(
        "Confirm account deletion",
        "Review your request below. Confirming starts a 30-day recovery period, signs you out, and pauses access to your owned farms.",
        include_form=True,
    )


@router.post(
    "/account-deletion/confirm",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def confirm_account_deletion(
    request: Request,
    service: DataDeletionService = Depends(get_data_deletion_service),
) -> HTMLResponse:
    body = await request.body()
    if len(body) > 1024:
        return _deletion_confirmation_page(
            "Confirmation link unavailable",
            "This confirmation link is invalid or has expired. Request a new link from Account & access.",
            include_form=False,
            response_status=status.HTTP_400_BAD_REQUEST,
        )
    form = parse_qs(body.decode("utf-8", errors="replace"), strict_parsing=False)
    token = form.get("token", [""])[0]
    if len(token) < 40 or len(token) > 128:
        return _deletion_confirmation_page(
            "Confirmation link unavailable",
            "This confirmation link is invalid or has expired. Request a new link from Account & access.",
            include_form=False,
            response_status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        scheduled_for = await service.confirm_account_deletion(token)
    except ConflictError:
        return _deletion_confirmation_page(
            "Confirmation link unavailable",
            "This confirmation link is invalid or has expired. Request a new link from Account & access.",
            include_form=False,
            response_status=status.HTTP_400_BAD_REQUEST,
        )
    return _deletion_confirmation_page(
        "Account deletion confirmed",
        f"Your account and owned farms are scheduled for deletion on {scheduled_for.strftime('%B %d, %Y')}. "
        "You have been signed out and cannot sign in during the 30-day recovery period. "
        "To restore, use Restore scheduled account deletion on the sign-in screen with your email and password.",
        include_form=False,
    )


def _deletion_confirmation_page(
    title: str,
    message: str,
    *,
    include_form: bool,
    response_status: int = status.HTTP_200_OK,
) -> HTMLResponse:
    action = (
        '<form method="post" autocomplete="off">'
        '<input type="hidden" name="token" id="confirmation-token">'
        '<button type="submit">Confirm deletion</button></form>'
        '<p id="confirmation-error" role="alert"></p>'
        "<script>"
        "const params=new URLSearchParams(window.location.hash.slice(1));"
        "const token=params.get('token')||'';"
        "document.getElementById('confirmation-token').value=token;"
        "history.replaceState(null,'',window.location.pathname);"
        "if(!token){document.querySelector('button').disabled=true;"
        "document.getElementById('confirmation-error').textContent="
        "'The confirmation link is incomplete. Request a new link from FarmTrack.';}"
        "</script>"
        if include_form
        else ""
    )
    html = (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>FarmTrack account deletion</title>"
        "<meta name=\"referrer\" content=\"no-referrer\">"
        "<style>body{font-family:Arial,sans-serif;background:#f3f6f2;color:#243128;"
        "margin:0;padding:24px}.card{max-width:520px;margin:8vh auto;background:white;"
        "padding:28px;border:1px solid #e3e9e1;border-radius:14px}h1{font-size:22px}"
        "p{line-height:1.6;color:#536157}button{background:#a33232;color:white;border:0;"
        "border-radius:8px;padding:13px 20px;font-weight:bold;font-size:16px}"
        "button:disabled{opacity:.5}</style></head><body><main class=\"card\">"
        "<strong>FarmTrack</strong>"
        f"<h1>{title}</h1><p>{message}</p>{action}"
        "</main></body></html>"
    )
    return HTMLResponse(
        html,
        status_code=response_status,
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'unsafe-inline'; "
                "script-src 'unsafe-inline'; form-action 'self'; "
                "base-uri 'none'; frame-ancestors 'none'"
            ),
        },
    )


@router.post(
    "/account-deletion/restore",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def restore_account_deletion(
    request: AccountRestoreRequest,
    service: DataDeletionService = Depends(get_data_deletion_service),
) -> Response:
    await service.restore_account(
        email=str(request.email),
        password=request.password,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
