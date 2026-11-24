from pathlib import Path as FilePath
from uuid import UUID
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import FileResponse, HTMLResponse, RedirectResponse

from app.core.database import get_database_session
from app.dependencies.auth import get_current_user
from app.dependencies.app_release import require_app_release_admin
from app.models.user import User
from app.schemas.app_release import (
    AppReleaseCreate,
    AppReleaseResponse,
    AppUpdateCheckResponse,
    BulkDownloadInvitationRequest,
    BulkDownloadInvitationResponse,
    DownloadInvitationRecordResponse,
    DownloadInvitationRequest,
    DownloadInvitationResponse,
    GitHubReleaseAssetResponse,
    ReleaseRecipientPageResponse,
    ReleaseShareInvitationResponse,
    WhatsAppInvitationRequest,
    WhatsAppInvitationResponse,
)
from app.services.app_release_service import AppReleaseService
from app.services.email_gateway_service import FarmTrackEmailService
from app.presentation.dependencies.services import get_email_gateway_service

router = APIRouter(tags=["App Releases"])


@router.get(
    "/app-releases/updates/latest",
    response_model=AppUpdateCheckResponse,
)
async def check_latest_app_update(
    current_version_code: int = Query(gt=0),
    _current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_database_session),
) -> AppUpdateCheckResponse:
    return await AppReleaseService(session).check_for_app_update(
        current_version_code=current_version_code,
    )


@router.get(
    "/app-releases/updates/{release_id}/download",
    response_class=Response,
)
async def download_authenticated_app_update(
    release_id: UUID,
    _current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_database_session),
) -> Response:
    return await AppReleaseService(
        session
    ).create_authenticated_update_download_response(release_id)


@router.post(
    "/app-releases",
    response_model=AppReleaseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_app_release(
    request: AppReleaseCreate,
    _admin: User = Depends(require_app_release_admin),
    session: AsyncSession = Depends(get_database_session),
) -> AppReleaseResponse:
    release = await AppReleaseService(session).register_release(request)
    return AppReleaseResponse.model_validate(release)


@router.get(
    "/app-releases",
    response_model=list[AppReleaseResponse],
)
async def list_app_releases(
    _admin: User = Depends(require_app_release_admin),
    session: AsyncSession = Depends(get_database_session),
) -> list[AppReleaseResponse]:
    releases = await AppReleaseService(session).list_releases()
    return [AppReleaseResponse.model_validate(release) for release in releases]


@router.get(
    "/app-releases/recipients",
    response_model=ReleaseRecipientPageResponse,
)
async def list_release_recipients(
    search: str = Query(default="", max_length=100),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _admin: User = Depends(require_app_release_admin),
    session: AsyncSession = Depends(get_database_session),
) -> ReleaseRecipientPageResponse:
    return await AppReleaseService(session).list_release_recipients(
        search=search,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/app-releases/github-assets",
    response_model=list[GitHubReleaseAssetResponse],
)
async def list_github_release_assets(
    tag: str = Query(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    ),
    _admin: User = Depends(require_app_release_admin),
    session: AsyncSession = Depends(get_database_session),
) -> list[GitHubReleaseAssetResponse]:
    assets = await AppReleaseService(session).list_github_release_assets(tag)
    return [GitHubReleaseAssetResponse.model_validate(asset) for asset in assets]


@router.get(
    "/app-releases/{release_id}/invitations",
    response_model=list[DownloadInvitationRecordResponse],
)
async def list_app_release_invitations(
    release_id: UUID,
    _admin: User = Depends(require_app_release_admin),
    session: AsyncSession = Depends(get_database_session),
) -> list[DownloadInvitationRecordResponse]:
    invitations = await AppReleaseService(session).list_download_invitations(
        release_id
    )
    return [
        DownloadInvitationRecordResponse.model_validate(invitation)
        for invitation in invitations
    ]


@router.post(
    "/app-releases/{release_id}/invitations",
    response_model=DownloadInvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def invite_app_download(
    release_id: UUID,
    request: DownloadInvitationRequest,
    response: Response,
    _admin: User = Depends(require_app_release_admin),
    session: AsyncSession = Depends(get_database_session),
    email_service: FarmTrackEmailService = Depends(get_email_gateway_service),
) -> DownloadInvitationResponse:
    response.headers["Cache-Control"] = "no-store"
    token, download_password = (
        await AppReleaseService(
            session,
            email_service=email_service,
        ).send_download_invitation(
            release_id=release_id,
            recipient_email=str(request.recipient_email),
        )
    )
    return DownloadInvitationResponse(
        id=token.id,
        recipient_email=token.recipient_email,
        download_password=download_password,
        delivery_status="sent",
        expires_at=token.expires_at,
    )


@router.post(
    "/app-releases/{release_id}/invitations/whatsapp",
    response_model=WhatsAppInvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def prepare_whatsapp_download_invitation(
    release_id: UUID,
    request: WhatsAppInvitationRequest,
    response: Response,
    _admin: User = Depends(require_app_release_admin),
    session: AsyncSession = Depends(get_database_session),
) -> WhatsAppInvitationResponse:
    response.headers["Cache-Control"] = "no-store"
    return await AppReleaseService(session).prepare_whatsapp_download_invitation(
        release_id=release_id,
        request=request,
    )


@router.post(
    "/app-releases/{release_id}/invitations/share",
    response_model=ReleaseShareInvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def prepare_release_share_invitation(
    release_id: UUID,
    response: Response,
    _admin: User = Depends(require_app_release_admin),
    session: AsyncSession = Depends(get_database_session),
) -> ReleaseShareInvitationResponse:
    response.headers["Cache-Control"] = "no-store"
    return await AppReleaseService(session).prepare_release_share_invitation(
        release_id=release_id,
    )


@router.get(
    "/app-releases/share-preview.png",
    response_class=FileResponse,
    include_in_schema=False,
)
async def get_release_share_preview_image() -> FileResponse:
    image_path = (
        FilePath(__file__).resolve().parents[3]
        / "static"
        / "farmtrack-share-preview.png"
    )
    return FileResponse(
        image_path,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.post(
    "/app-releases/{release_id}/invitations/bulk",
    response_model=BulkDownloadInvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def invite_multiple_app_downloads(
    release_id: UUID,
    request: BulkDownloadInvitationRequest,
    response: Response,
    _admin: User = Depends(require_app_release_admin),
    session: AsyncSession = Depends(get_database_session),
    email_service: FarmTrackEmailService = Depends(get_email_gateway_service),
) -> BulkDownloadInvitationResponse:
    response.headers["Cache-Control"] = "no-store"
    results = await AppReleaseService(
        session,
        email_service=email_service,
    ).send_bulk_download_invitations(
        release_id=release_id,
        request=request,
    )
    return BulkDownloadInvitationResponse(results=results)


@router.delete(
    "/app-releases/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def revoke_app_download_invitation(
    invitation_id: UUID,
    _admin: User = Depends(require_app_release_admin),
    session: AsyncSession = Depends(get_database_session),
) -> Response:
    await AppReleaseService(session).revoke_download_invitation(invitation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/downloads/{token}",
    response_class=Response,
)
@router.post(
    "/downloads/{token}",
    response_class=Response,
)
async def download_app(
    request: Request,
    token: str = Path(min_length=32, max_length=128),
    session: AsyncSession = Depends(get_database_session),
) -> Response:
    service = AppReleaseService(session)
    if request.method == "GET":
        return await service.create_download_password_page(token)
    if request.method != "POST":
        return Response(status_code=status.HTTP_405_METHOD_NOT_ALLOWED)
    if "application/x-www-form-urlencoded" not in request.headers.get(
        "content-type", ""
    ).lower():
        return await service.create_download_password_page(
            token,
            error="Submit the password using the download form.",
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        )
    body = await request.body()
    if len(body) > 2048:
        return await service.create_download_password_page(
            token,
            error="The password was not accepted. Please try again.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    fields = parse_qs(body.decode("utf-8", errors="replace"))
    password = fields.get("password", [""])[0]
    download_response = await service.create_download_response(
        token,
        password=password,
    )
    if isinstance(download_response, RedirectResponse):
        download_url = download_response.headers.get("location")
        if download_url is None:
            return download_response
        return service.create_download_success_page(download_url)
    return download_response


@router.get(
    "/downloads/{token}/share",
    response_class=Response,
    include_in_schema=False,
)
async def download_app_share_page(
    token: str = Path(min_length=32, max_length=128),
    session: AsyncSession = Depends(get_database_session),
) -> Response:
    return await AppReleaseService(session).create_download_share_page(token)
