from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.core.database import get_database_session
from app.dependencies.app_release import require_app_release_admin
from app.models.user import User
from app.schemas.app_release import (
    AppReleaseCreate,
    AppReleaseResponse,
    BulkDownloadInvitationRequest,
    BulkDownloadInvitationResponse,
    DownloadInvitationRecordResponse,
    DownloadInvitationRequest,
    DownloadInvitationResponse,
    GitHubReleaseAssetResponse,
    ReleaseRecipientPageResponse,
    WhatsAppInvitationRequest,
    WhatsAppInvitationResponse,
)
from app.services.app_release_service import AppReleaseService

router = APIRouter(tags=["App Releases"])


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
    _admin: User = Depends(require_app_release_admin),
    session: AsyncSession = Depends(get_database_session),
) -> DownloadInvitationResponse:
    token = await AppReleaseService(session).send_download_invitation(
        release_id=release_id,
        recipient_email=str(request.recipient_email),
    )
    return DownloadInvitationResponse(
        id=token.id,
        recipient_email=token.recipient_email,
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
    _admin: User = Depends(require_app_release_admin),
    session: AsyncSession = Depends(get_database_session),
) -> WhatsAppInvitationResponse:
    return await AppReleaseService(session).prepare_whatsapp_download_invitation(
        release_id=release_id,
        request=request,
    )


@router.post(
    "/app-releases/{release_id}/invitations/bulk",
    response_model=BulkDownloadInvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def invite_multiple_app_downloads(
    release_id: UUID,
    request: BulkDownloadInvitationRequest,
    _admin: User = Depends(require_app_release_admin),
    session: AsyncSession = Depends(get_database_session),
) -> BulkDownloadInvitationResponse:
    results = await AppReleaseService(session).send_bulk_download_invitations(
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
async def download_app(
    token: str = Path(min_length=32, max_length=128),
    session: AsyncSession = Depends(get_database_session),
) -> Response:
    return await AppReleaseService(session).create_download_response(token)
