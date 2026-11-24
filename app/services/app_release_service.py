from datetime import datetime, timedelta, timezone
import hashlib
import html
import re
import secrets
from urllib.parse import quote
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import HTMLResponse, Response

from app.core.config import settings
from app.core.exceptions import AppError, ConflictError, ResourceNotFoundError
from app.core.logging import get_application_logger
from app.models.app_release import AppRelease
from app.models.download_token import DownloadToken
from app.repositories.app_release_repository import (
    AppReleaseRepository,
    DownloadTokenRepository,
)
from app.repositories.app_release_recipient_repository import (
    AppReleaseRecipientRepository,
)
from app.schemas.app_release import (
    AppReleaseCreate,
    AppUpdateCheckResponse,
    AvailableAppUpdate,
    BulkDownloadInvitationRequest,
    BulkDownloadInvitationResult,
    ReleaseRecipientFarmResponse,
    ReleaseRecipientPageResponse,
    ReleaseRecipientResponse,
    ReleaseShareInvitationResponse,
    WhatsAppInvitationResponse,
    WhatsAppInvitationRequest,
)
from app.services.github_release_storage_service import GitHubReleaseStorageService
from app.services.email_gateway_service import FarmTrackEmailService

logger = get_application_logger()
DOWNLOAD_PASSWORD_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


class AppReleaseService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        storage_service: GitHubReleaseStorageService | None = None,
        email_service: FarmTrackEmailService | None = None,
        recipient_repository: AppReleaseRecipientRepository | None = None,
    ):
        self.session = session
        self.releases = AppReleaseRepository(session)
        self.tokens = DownloadTokenRepository(session)
        self.recipients = recipient_repository or AppReleaseRecipientRepository(session)
        self.storage_service = storage_service or GitHubReleaseStorageService()
        self.email_service = email_service or FarmTrackEmailService()

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

    async def check_for_app_update(
        self,
        *,
        current_version_code: int,
    ) -> AppUpdateCheckResponse:
        release = await self.releases.get_latest_active_release("android")
        if release is None or release.version_code <= current_version_code:
            return AppUpdateCheckResponse(update_available=False)
        return AppUpdateCheckResponse(
            update_available=True,
            release=AvailableAppUpdate(
                id=release.id,
                version=release.version,
                version_code=release.version_code,
                file_name=release.file_name,
                file_size=release.file_size,
                release_notes=release.release_notes,
            ),
        )

    async def create_authenticated_update_download_response(
        self,
        release_id: UUID,
    ) -> Response:
        release = await self.releases.get_release(release_id)
        if (
            release is None
            or not release.is_active
            or not release.is_latest
            or release.github_asset_id is None
        ):
            raise ResourceNotFoundError("This app update is no longer available.")
        return await self.storage_service.create_download_response(
            release.github_asset_id,
            file_name=release.file_name,
            follow_redirects=True,
        )

    async def list_github_release_assets(
        self,
        tag: str,
    ) -> list[dict[str, int | str]]:
        return await self.storage_service.list_release_assets(tag)

    async def list_release_recipients(
        self,
        *,
        search: str,
        limit: int,
        offset: int,
    ) -> ReleaseRecipientPageResponse:
        users, total, farms_by_user = await self.recipients.list_recipients(
            search=search,
            limit=limit,
            offset=offset,
        )
        return ReleaseRecipientPageResponse(
            items=[
                ReleaseRecipientResponse(
                    user_id=user.id,
                    email=user.email,
                    farms=[
                        ReleaseRecipientFarmResponse(
                            farm_id=farm.id,
                            farm_name=farm.name,
                            phone_number=farm.phone_number,
                            email=farm.email,
                        )
                        for farm in farms_by_user.get(user.id, [])
                    ],
                )
                for user in users
            ],
            total=total,
            offset=offset,
            limit=limit,
        )

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
    ) -> tuple[DownloadToken, str]:
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
        download_password = self._new_download_password()
        token = DownloadToken(
            token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
            password_hash=self._hash_download_password(download_password),
            release_id=release.id,
            recipient_email=recipient_email.strip().lower(),
            delivery_channel="email",
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
                download_password=download_password,
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
        return token, download_password

    async def prepare_whatsapp_download_invitation(
        self,
        *,
        release_id: UUID,
        request: WhatsAppInvitationRequest,
    ) -> WhatsAppInvitationResponse:
        release = await self.releases.get_release(release_id)
        if release is None or not release.is_active:
            raise ResourceNotFoundError("Active app release not found.")
        if settings.app_public_base_url is None:
            raise AppError(
                "APP_PUBLIC_URL_UNAVAILABLE",
                "Download invitations are not configured.",
                503,
            )

        phone = self._whatsapp_phone(request.phone_number, "recipient")
        raw_token = secrets.token_urlsafe(32)
        download_password = self._new_download_password()
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=settings.download_token_expiry_days
        )
        token = DownloadToken(
            token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
            password_hash=self._hash_download_password(download_password),
            release_id=release.id,
            recipient_email=None,
            recipient_phone=phone,
            delivery_channel="whatsapp",
            delivery_status="prepared",
            expires_at=expires_at,
        )
        self.session.add(token)
        await self.session.commit()

        download_url = (
            f"{settings.app_public_base_url.rstrip('/')}"
            f"/api/v1/downloads/{raw_token}"
        )
        share_url = f"{download_url}/share"
        share_message = self._release_invitation_message(release)
        whatsapp_message = f"{share_message}\n{share_url}"
        return WhatsAppInvitationResponse(
            id=token.id,
            recipient_phone=phone,
            delivery_channel="whatsapp",
            delivery_status="prepared",
            download_password=download_password,
            whatsapp_url=f"https://wa.me/{phone}?text={quote(whatsapp_message)}",
            share_message=share_message,
            download_url=download_url,
            share_url=share_url,
            preview_image_url=(
                f"{settings.app_public_base_url.rstrip('/')}"
                "/api/v1/app-releases/share-preview.png"
            ),
            expires_at=expires_at,
        )

    async def prepare_release_share_invitation(
        self,
        *,
        release_id: UUID,
    ) -> ReleaseShareInvitationResponse:
        release = await self.releases.get_release(release_id)
        if release is None or not release.is_active:
            raise ResourceNotFoundError("Active app release not found.")
        if settings.app_public_base_url is None:
            raise AppError(
                "APP_PUBLIC_URL_UNAVAILABLE",
                "Download invitations are not configured.",
                503,
            )

        raw_token = secrets.token_urlsafe(32)
        download_password = self._new_download_password()
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=settings.download_token_expiry_days
        )
        token = DownloadToken(
            token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
            password_hash=self._hash_download_password(download_password),
            release_id=release.id,
            recipient_email=None,
            recipient_phone=None,
            delivery_channel="whatsapp",
            delivery_status="prepared",
            expires_at=expires_at,
        )
        self.session.add(token)
        await self.session.commit()

        base_url = settings.app_public_base_url.rstrip("/")
        download_url = f"{base_url}/api/v1/downloads/{raw_token}"
        share_url = f"{download_url}/share"
        preview_image_url = (
            f"{base_url}/api/v1/app-releases/share-preview.png"
        )
        share_message = self._release_invitation_message(release)
        whatsapp_message = f"{share_message}\n{share_url}"
        return ReleaseShareInvitationResponse(
            id=token.id,
            delivery_channel="whatsapp",
            delivery_status="prepared",
            download_password=download_password,
            whatsapp_url=f"https://wa.me/?text={quote(whatsapp_message)}",
            share_message=share_message,
            download_url=download_url,
            share_url=share_url,
            preview_image_url=preview_image_url,
            expires_at=expires_at,
        )

    async def create_download_share_page(self, raw_token: str) -> HTMLResponse:
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        token = await self.tokens.get_with_release(token_hash)
        token = self._validate_download_token(token)

        release = token.release
        base_url = settings.app_public_base_url
        if base_url is None:
            raise AppError(
                "APP_PUBLIC_URL_UNAVAILABLE",
                "Download invitations are not configured.",
                503,
            )
        base_url = base_url.rstrip("/")
        share_url = f"{base_url}/api/v1/downloads/{raw_token}/share"
        download_url = f"{base_url}/api/v1/downloads/{raw_token}"
        image_url = f"{base_url}/api/v1/app-releases/share-preview.png"
        title = f"FarmTrack for Android — Version {html.escape(release.version)}"
        description = (
            "Manage your farm with FarmTrack. Download the Android app using "
            "this private invitation link."
        )
        if release.release_notes:
            description += f" What's new: {release.release_notes.strip()}"
        description = html.escape(description[:300])
        document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex,nofollow">
  <title>{title}</title>
  <meta name="description" content="{description}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="FarmTrack">
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{description}">
  <meta property="og:url" content="{html.escape(share_url, quote=True)}">
  <meta property="og:image" content="{html.escape(image_url, quote=True)}">
  <meta property="og:image:secure_url" content="{html.escape(image_url, quote=True)}">
  <meta property="og:image:type" content="image/png">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{title}">
  <meta name="twitter:description" content="{description}">
  <meta name="twitter:image" content="{html.escape(image_url, quote=True)}">
  <style>
    body {{ margin: 0; min-height: 100vh; display: grid; place-items: center;
      padding: 24px; box-sizing: border-box; background: #f2f6f2;
      color: #23392b; font: 16px system-ui, sans-serif; }}
    main {{ width: min(100%, 520px); overflow: hidden; border: 1px solid #dce8df;
      border-radius: 20px; background: white; box-shadow: 0 16px 48px #173d2b18; }}
    img {{ display: block; width: 100%; aspect-ratio: 1200 / 630; object-fit: cover; }}
    section {{ padding: 24px; }}
    h1 {{ margin: 0 0 10px; font-size: 24px; }}
    p {{ color: #617166; line-height: 1.6; }}
    a {{ display: inline-flex; min-height: 48px; align-items: center; padding: 0 20px;
      border-radius: 10px; background: #26734a; color: white; font-weight: 700;
      text-decoration: none; }}
  </style>
</head>
<body>
  <main>
    <img src="{html.escape(image_url, quote=True)}" alt="FarmTrack farm management app">
    <section>
      <h1>{title}</h1>
      <p>{description}</p>
      <a href="{html.escape(download_url, quote=True)}">Download FarmTrack for Android</a>
    </section>
  </main>
</body>
</html>"""
        return HTMLResponse(
            document,
            headers={"Cache-Control": "public, max-age=300"},
        )

    async def create_download_password_page(
        self,
        raw_token: str,
        *,
        error: str | None = None,
        status_code: int = 200,
    ) -> HTMLResponse:
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        token = await self.tokens.get_with_release(token_hash)
        token = self._validate_download_token(token)
        version = html.escape(token.release.version)
        action = html.escape(
            f"{settings.app_public_base_url.rstrip('/')}/api/v1/downloads/{raw_token}",
            quote=True,
        ) if settings.app_public_base_url else f"/api/v1/downloads/{raw_token}"
        error_message = (
            f'<p class="error" role="alert">{html.escape(error)}</p>'
            if error
            else ""
        )
        document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex,nofollow">
  <title>Download FarmTrack for Android</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; min-height: 100vh; display: grid; place-items: center;
      padding: 24px; background: #f2f6f2; color: #23392b;
      font: 16px system-ui, sans-serif; }}
    main {{ width: min(100%, 440px); padding: 28px; border: 1px solid #dce8df;
      border-radius: 20px; background: white; box-shadow: 0 16px 48px #173d2b18; }}
    .brand {{ color: #26734a; font-size: 13px; font-weight: 800;
      letter-spacing: 1.5px; text-transform: uppercase; }}
    h1 {{ margin: 14px 0 8px; font-size: 25px; }}
    p {{ color: #617166; line-height: 1.55; }}
    label {{ display: block; margin: 20px 0 7px; font-size: 14px; font-weight: 700; }}
    input {{ width: 100%; min-height: 48px; padding: 10px 12px;
      border: 1px solid #cbd9ce; border-radius: 10px; font: inherit; }}
    button {{ width: 100%; min-height: 48px; margin-top: 14px; border: 0;
      border-radius: 10px; background: #26734a; color: white; font: inherit;
      font-weight: 700; cursor: pointer; }}
    button:disabled {{ cursor: wait; opacity: .85; }}
    .button-content {{ display: inline-flex; align-items: center; gap: 10px; }}
    .spinner {{ display: none; width: 18px; height: 18px; border: 2px solid #ffffff66;
      border-top-color: white; border-radius: 50%; }}
    button.is-loading .spinner {{ display: inline-block; animation: spin .75s linear infinite; }}
    .form-status {{ min-height: 24px; margin: 12px 0 0; color: #26734a;
      font-size: 14px; font-weight: 650; }}
    .error {{ padding: 10px 12px; border-radius: 9px; background: #fff1ef;
      color: #a13e39; font-size: 14px; animation: reject .45s ease both; }}
    .hint {{ margin-bottom: 0; font-size: 13px; }}
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
    @keyframes reject {{ 0%, 100% {{ transform: translateX(0); }}
      20%, 60% {{ transform: translateX(-6px); }}
      40%, 80% {{ transform: translateX(6px); }} }}
    @media (prefers-reduced-motion: reduce) {{
      *, *::before, *::after {{ animation-duration: .01ms !important;
        animation-iteration-count: 1 !important; scroll-behavior: auto !important; }}
    }}
  </style>
</head>
<body>
  <main>
    <div class="brand">FarmTrack</div>
    <h1>Download FarmTrack</h1>
    <p>Enter the invitation password to download version {version} for Android.</p>
    {error_message}
    <form method="post" action="{action}" autocomplete="off">
      <label for="password">Invitation password</label>
      <input id="password" name="password" type="password" required
        minlength="16" maxlength="16" autocapitalize="characters"
        autocomplete="one-time-code" autofocus>
      <button id="submit-button" type="submit">
        <span class="button-content"><span class="spinner" aria-hidden="true"></span>
          <span id="button-label">Verify and download APK</span></span>
      </button>
      <p class="form-status" id="form-status" role="status" aria-live="polite"></p>
    </form>
    <p class="hint">Ask the person who sent this link for the separate password.</p>
  </main>
  <script>
    const form = document.querySelector("form");
    const button = document.querySelector("#submit-button");
    const buttonLabel = document.querySelector("#button-label");
    const formStatus = document.querySelector("#form-status");
    form.addEventListener("submit", (event) => {{
      if (form.dataset.submitting === "true") {{
        event.preventDefault();
        return;
      }}
      form.dataset.submitting = "true";
      button.disabled = true;
      button.classList.add("is-loading");
      buttonLabel.textContent = "Verifying…";
      formStatus.textContent = "Checking your invitation password";
    }});
  </script>
</body>
</html>"""
        return HTMLResponse(
            document,
            status_code=status_code,
            headers={"Cache-Control": "no-store"},
        )

    @staticmethod
    def create_download_success_page(download_url: str) -> HTMLResponse:
        safe_download_url = html.escape(download_url, quote=True)
        document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex,nofollow">
  <meta http-equiv="refresh" content="1.2;url={safe_download_url}">
  <title>Password verified - FarmTrack</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; min-height: 100vh; display: grid; place-items: center;
      padding: 24px; background: #f2f6f2; color: #23392b;
      font: 16px system-ui, sans-serif; }}
    main {{ width: min(100%, 440px); padding: 34px 28px; border: 1px solid #dce8df;
      border-radius: 20px; background: white; text-align: center;
      box-shadow: 0 16px 48px #173d2b18; animation: arrive .4s ease both; }}
    .success-icon {{ width: 72px; height: 72px; margin: 0 auto 20px;
      color: #26734a; }}
    .success-icon circle {{ stroke-dasharray: 190; stroke-dashoffset: 190;
      animation: draw-circle .55s ease-out .1s forwards; }}
    .success-icon path {{ stroke-dasharray: 40; stroke-dashoffset: 40;
      animation: draw-check .35s ease-out .55s forwards; }}
    .brand {{ color: #26734a; font-size: 13px; font-weight: 800;
      letter-spacing: 1.5px; text-transform: uppercase; }}
    h1 {{ margin: 12px 0 8px; font-size: 25px; }}
    p {{ color: #617166; line-height: 1.55; }}
    a {{ display: inline-flex; justify-content: center; align-items: center;
      min-height: 48px; width: 100%; margin-top: 12px; border-radius: 10px;
      background: #26734a; color: white; font-weight: 700; text-decoration: none; }}
    @keyframes arrive {{ from {{ opacity: 0; transform: translateY(10px) scale(.98); }}
      to {{ opacity: 1; transform: translateY(0) scale(1); }} }}
    @keyframes draw-circle {{ to {{ stroke-dashoffset: 0; }} }}
    @keyframes draw-check {{ to {{ stroke-dashoffset: 0; }} }}
    @media (prefers-reduced-motion: reduce) {{
      *, *::before, *::after {{ animation-duration: .01ms !important;
        animation-iteration-count: 1 !important; }}
    }}
  </style>
</head>
<body>
  <main>
    <svg class="success-icon" viewBox="0 0 72 72" fill="none"
      aria-hidden="true">
      <circle cx="36" cy="36" r="30" stroke="currentColor" stroke-width="4"/>
      <path d="M22 37l9 9 19-20" stroke="currentColor" stroke-width="4"
        stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
    <div class="brand">FarmTrack</div>
    <h1>Password verified</h1>
    <p>Your invitation is valid. Your APK download is starting.</p>
    <a id="download-link" href="{safe_download_url}">Continue to download</a>
  </main>
  <script>
    window.setTimeout(() => {{
      window.location.replace(document.querySelector("#download-link").href);
    }}, 1100);
  </script>
</body>
</html>"""
        return HTMLResponse(document, headers={"Cache-Control": "no-store"})

    async def send_bulk_download_invitations(
        self,
        *,
        release_id: UUID,
        request: BulkDownloadInvitationRequest,
    ) -> list[BulkDownloadInvitationResult]:
        release = await self.releases.get_release(release_id)
        if release is None or not release.is_active:
            raise ResourceNotFoundError("Active app release not found.")
        if settings.app_public_base_url is None:
            raise AppError(
                "APP_PUBLIC_URL_UNAVAILABLE",
                "Download invitations are not configured.",
                503,
            )

        wants_email = request.channel in {"email", "both"}
        wants_whatsapp = request.channel in {"whatsapp", "both"}
        if wants_email and not self.email_service.is_configured and not wants_whatsapp:
            raise AppError(
                "EMAIL_DELIVERY_UNAVAILABLE",
                "Email invitations are not configured.",
                503,
            )

        user_ids = [recipient.user_id for recipient in request.recipients]
        if len(set(user_ids)) != len(user_ids):
            raise AppError(
                "DUPLICATE_INVITATION_RECIPIENT",
                "Each registered user can only be selected once.",
                422,
            )
        users, farms_by_user = await self.recipients.get_recipients(user_ids)
        missing_users = set(user_ids) - set(users)
        if missing_users:
            raise ResourceNotFoundError(
                "One or more selected accounts are unavailable."
            )

        prepared: list[tuple[UUID, str, str | None]] = []
        for recipient in request.recipients:
            user = users[recipient.user_id]
            whatsapp_phone = None
            if wants_whatsapp:
                available_farms = farms_by_user.get(user.id, [])
                farm = next(
                    (
                        item
                        for item in available_farms
                        if item.id == recipient.farm_id
                    ),
                    None,
                )
                if farm is None or not farm.phone_number:
                    raise AppError(
                        "WHATSAPP_PHONE_UNAVAILABLE",
                        f"No selected farm phone number is available for {user.email}.",
                        422,
                    )
                whatsapp_phone = self._whatsapp_phone(farm.phone_number, user.email)
            prepared.append((user.id, user.email.strip().lower(), whatsapp_phone))

        results: list[BulkDownloadInvitationResult] = []
        for user_id, recipient_email, whatsapp_phone in prepared:
            wants_whatsapp_for_recipient = wants_whatsapp and whatsapp_phone is not None
            token_status = (
                "pending"
                if wants_email and self.email_service.is_configured
                else "prepared"
            )
            raw_token = secrets.token_urlsafe(32)
            download_password = self._new_download_password()
            token = DownloadToken(
                token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
                password_hash=self._hash_download_password(download_password),
                release_id=release.id,
                recipient_email=recipient_email,
                delivery_channel=request.channel,
                delivery_status=token_status,
                expires_at=datetime.now(timezone.utc)
                + timedelta(days=settings.download_token_expiry_days),
            )
            self.session.add(token)
            await self.session.commit()
            download_url = (
                f"{settings.app_public_base_url.rstrip('/')}"
                f"/api/v1/downloads/{raw_token}"
            )
            share_url = f"{download_url}/share"
            whatsapp_url = None
            if wants_whatsapp_for_recipient:
                message = (
                    f"{self._release_invitation_message(release)}\n{share_url}"
                )
                whatsapp_url = (
                    f"https://wa.me/{whatsapp_phone}?text={quote(message)}"
                )

            email_status = "not_requested"
            error = None
            if wants_email:
                if not self.email_service.is_configured:
                    email_status = "failed"
                    error = "Email delivery is not configured; use the prepared WhatsApp link."
                else:
                    email_status = "sent"
                    try:
                        await self.email_service.send_release_download_invitation(
                            recipient_email=recipient_email,
                            version=release.version,
                            release_notes=release.release_notes,
                            download_url=download_url,
                            download_password=download_password,
                            expires_at=token.expires_at,
                            delivery_id=token.id,
                        )
                        token.delivery_status = "sent"
                        await self.session.commit()
                    except Exception as exc:
                        await self.session.rollback()
                        failed_token = await self.tokens.get_by_hash_for_update(
                            token.token_hash
                        )
                        if failed_token is not None:
                            if wants_whatsapp_for_recipient:
                                failed_token.delivery_status = "prepared"
                            else:
                                failed_token.delivery_status = "failed"
                                failed_token.revoked_at = datetime.now(timezone.utc)
                            await self.session.commit()
                        email_status = "failed"
                        error = "The email could not be sent."
                        logger.warning(
                            "app_release_bulk_download_email_failed",
                            extra={
                                "event": "app_release_bulk_download_email_failed",
                                "release_id": str(release.id),
                                "download_token_id": str(token.id),
                                "recipient_user_id": str(user_id),
                                "error_type": type(exc).__name__,
                            },
                        )

            results.append(
                BulkDownloadInvitationResult(
                    user_id=user_id,
                    recipient_email=recipient_email,
                    email_status=email_status,
                    download_password=(
                        download_password
                        if email_status == "sent" or wants_whatsapp_for_recipient
                        else None
                    ),
                    whatsapp_url=whatsapp_url,
                    error=error,
                )
            )
        return results

    @staticmethod
    def _release_invitation_message(release: AppRelease) -> str:
        message_parts = [
            "Hi! 👋 I’d like to invite you to try FarmTrack, an Android app "
            "for managing your farm.",
            f"Version {release.version} is ready to download.",
        ]
        if release.release_notes:
            message_parts.extend(["", "What’s new:", release.release_notes.strip()])
        message_parts.extend(
            [
                "",
                "Open your private download link below, then enter the separate "
                "password I will send you:",
            ]
        )
        return "\n".join(message_parts)

    @staticmethod
    def _whatsapp_phone(phone: str, email: str) -> str:
        digits = re.sub(r"\D", "", phone)
        if not 8 <= len(digits) <= 15 or digits.startswith("0"):
            raise AppError(
                "INVALID_WHATSAPP_PHONE",
                f"The farm phone number for {email} must include its country code.",
                422,
            )
        return digits

    async def create_download_response(
        self,
        raw_token: str,
        *,
        password: str,
    ) -> Response:
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        token = await self.tokens.get_with_release_for_update(token_hash)
        now = datetime.now(timezone.utc)
        token = self._validate_download_token(token, now=now)
        if not secrets.compare_digest(
            self._hash_download_password(password),
            token.password_hash,
        ):
            return await self.create_download_password_page(
                raw_token,
                error="That password is incorrect. Check it and try again.",
                status_code=401,
            )
        asset_id = token.release.github_asset_id
        if asset_id is None:
            raise AppError(
                "APP_RELEASE_UNAVAILABLE",
                "This app release is no longer available.",
                410,
            )

        response = await self.storage_service.create_download_response(
            asset_id,
            file_name=token.release.file_name,
        )
        token.last_accessed_at = now
        token.access_count += 1
        await self.session.commit()
        return response

    @staticmethod
    def _new_download_password() -> str:
        return "".join(
            secrets.choice(DOWNLOAD_PASSWORD_ALPHABET) for _ in range(16)
        )

    @staticmethod
    def _hash_download_password(password: str) -> str:
        return hashlib.sha256(password.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_download_token(
        token: DownloadToken | None,
        *,
        now: datetime | None = None,
    ) -> DownloadToken:
        if token is None:
            raise ResourceNotFoundError("This download link is invalid.")
        if token.delivery_status not in {"sent", "prepared"}:
            raise ResourceNotFoundError("This download link is invalid.")
        if token.revoked_at is not None or token.expires_at <= (
            now or datetime.now(timezone.utc)
        ):
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
        return token
        if token.release.github_asset_id is None:
            raise AppError(
                "APP_RELEASE_UNAVAILABLE",
                "This app release is no longer available.",
                410,
            )
