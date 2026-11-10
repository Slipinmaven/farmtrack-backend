from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.core.config import settings
from app.core.exceptions import AppError, ConflictError, ResourceNotFoundError
from app.core.logging import get_application_logger
from app.models.app_release import AppRelease
from app.models.download_token import DownloadToken
from app.repositories.app_release_repository import (
    AppReleaseRepository,
    DownloadTokenRepository,
)
from app.schemas.app_release import AppReleaseCreate
from app.services.github_release_storage_service import GitHubReleaseStorageService
from app.services.smtp_email_service import SMTPEmailService

logger = get_application_logger()


class AppReleaseService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        storage_service: GitHubReleaseStorageService | None = None,
        email_service: SMTPEmailService | None = None,
    ):
        self.session = session
        self.releases = AppReleaseRepository(session)
        self.tokens = DownloadTokenRepository(session)
        self.storage_service = storage_service or GitHubReleaseStorageService()
        self.email_service = email_service or SMTPEmailService()

    async def register_release(self, request: AppReleaseCreate) -> AppRelease:
        file_name, file_size = await self.storage_service.verify_asset(
            request.github_asset_id
        )
        if await self.releases.get_by_version_code(
            request.platform,
            request.version_code,
        ):
            raise ConflictError("This platform version code is already registered.")
        release = AppRelease(
            **request.model_dump(),
            file_name=file_name,
            file_size=file_size,
        )
        try:
            if release.is_latest:
                await self.releases.clear_latest(release.platform)
            await self.releases.create_release(release)
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(
                "This platform version code or GitHub asset is already registered."
            ) from exc
        return release

    async def list_releases(self) -> list[AppRelease]:
        return await self.releases.list_releases()

    async def list_github_release_assets(
        self,
        tag: str,
    ) -> list[dict[str, int | str]]:
        return await self.storage_service.list_release_assets(tag)

    async def list_download_invitations(
        self,
        release_id: UUID,
    ) -> list[DownloadToken]:
        release = await self.releases.get_release(release_id)
        if release is None:
            raise ResourceNotFoundError("App release not found.")
        return await self.tokens.list_for_release(release_id)

    async def revoke_download_invitation(self, token_id: UUID) -> None:
        token = await self.tokens.get_by_id_for_update(token_id)
        if token is None:
            raise ResourceNotFoundError("Download invitation not found.")
        if token.revoked_at is None:
            token.revoked_at = datetime.now(timezone.utc)
            await self.session.commit()

    async def send_download_invitation(
        self,
        *,
        release_id: UUID,
        recipient_email: str,
    ) -> DownloadToken:
        release = await self.releases.get_release(release_id)
        if release is None or not release.is_active:
            raise ResourceNotFoundError("Active app release not found.")
        if settings.app_public_base_url is None:
            raise AppError(
                "APP_PUBLIC_URL_UNAVAILABLE",
                "Download invitations are not configured.",
                503,
            )
        if not self.email_service.is_configured:
            raise AppError(
                "EMAIL_DELIVERY_UNAVAILABLE",
                "Download invitations are not configured.",
                503,
            )

        raw_token = secrets.token_urlsafe(32)
        token = DownloadToken(
            token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
            release_id=release.id,
            recipient_email=recipient_email.strip().lower(),
            delivery_status="pending",
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=settings.download_token_expiry_days),
        )
        token_hash = token.token_hash
        self.session.add(token)
        await self.session.commit()

        download_url = (
            f"{settings.app_public_base_url}/api/v1/downloads/{raw_token}"
        )
        try:
            await self.email_service.send_release_download_invitation(
                recipient_email=token.recipient_email,
                version=release.version,
                release_notes=release.release_notes,
                download_url=download_url,
                expires_at=token.expires_at,
                delivery_id=token.id,
            )
        except Exception as exc:
            await self.session.rollback()
            failed_token = await self.tokens.get_by_hash_for_update(token_hash)
            if failed_token is not None:
                failed_token.delivery_status = "failed"
                failed_token.revoked_at = datetime.now(timezone.utc)
                await self.session.commit()
            logger.warning(
                "app_release_download_email_failed",
                extra={
                    "event": "app_release_download_email_failed",
                    "release_id": str(release.id),
                    "download_token_id": str(token.id),
                    "error_type": type(exc).__name__,
                },
            )
            raise AppError(
                "DOWNLOAD_EMAIL_FAILED",
                "The download email could not be sent. Please try again.",
                502,
            ) from exc

        token.delivery_status = "sent"
        await self.session.commit()
        return token

    async def create_download_response(self, raw_token: str) -> Response:
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        token = await self.tokens.get_with_release_for_update(token_hash)
        now = datetime.now(timezone.utc)
        if token is None:
            raise ResourceNotFoundError("This download link is invalid.")
        if token.delivery_status != "sent":
            raise ResourceNotFoundError("This download link is invalid.")
        if token.revoked_at is not None or token.expires_at <= now:
            raise AppError(
                "DOWNLOAD_LINK_EXPIRED",
                "This download link has expired or been revoked.",
                410,
            )
        if not token.release.is_active:
            raise AppError(
                "APP_RELEASE_UNAVAILABLE",
                "This app release is no longer available.",
                410,
            )
        if token.release.github_asset_id is None:
            raise AppError(
                "APP_RELEASE_UNAVAILABLE",
                "This app release is no longer available.",
                410,
            )

        response = await self.storage_service.create_download_response(
            token.release.github_asset_id,
            file_name=token.release.file_name,
        )
        token.last_accessed_at = now
        token.access_count += 1
        await self.session.commit()
        return response
