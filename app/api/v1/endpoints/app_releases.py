from uuid import UUID

from fastapi import APIRouter, Depends, Path, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.core.database import get_database_session
from app.dependencies.app_release import require_app_release_admin
from app.models.user import User
from app.schemas.app_release import (
    AppReleaseCreate,
    AppReleaseResponse,
    DownloadInvitationRequest,
    DownloadInvitationResponse,
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
