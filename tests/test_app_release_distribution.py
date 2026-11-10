from datetime import datetime, timedelta, timezone
import hashlib
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from starlette.responses import RedirectResponse

from app.api.v1.endpoints.app_releases import router as app_release_router
from app.core.config import Settings, settings
from app.core.exceptions import (
    AppError,
    AuthorizationError,
    ConflictError,
    ResourceNotFoundError,
)
from app.dependencies.app_release import require_app_release_admin
from app.models.download_token import DownloadToken
from app.schemas.app_release import (
    AppReleaseCreate,
    BulkDownloadInvitationRequest,
    BulkInvitationRecipient,
    WhatsAppInvitationRequest,
)
from app.services.app_release_service import AppReleaseService
from app.services.github_release_storage_service import GitHubReleaseStorageService


def test_share_preview_image_is_available_as_public_png():
    application = FastAPI()
    application.include_router(app_release_router, prefix="/api/v1")

    with TestClient(application) as client:
        response = client.get("/api/v1/app-releases/share-preview.png")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_release_admin_emails_parse_comma_separated_environment_value(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
    monkeypatch.setenv("JWT_SECRET_KEY", "a" * 32)
    monkeypatch.setenv(
        "APP_RELEASE_ADMIN_EMAILS",
        "farmtrack.team@gmail.com, SECOND@example.com",
    )

    configured = Settings(_env_file=None)

    assert configured.app_release_admin_emails == [
        "farmtrack.team@gmail.com",
        "second@example.com",
    ]


class FakeSession:
    def __init__(self):
        self.added = []
        self.commits = 0
        self.rollbacks = 0

    def add(self, item):
        if getattr(item, "id", None) is None:
            item.id = uuid4()
        self.added.append(item)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


class FakeReleaseRepository:
    def __init__(self, release=None, duplicate=False):
        self.release = release
        self.duplicate = duplicate
        self.latest_cleared = []

    async def list_releases(self):
        return [self.release] if self.release else []

    async def get_release(self, _release_id):
        return self.release

    async def get_by_version_code(self, _platform, _version_code):
        return self.release if self.duplicate else None

    async def clear_latest(self, platform):
        self.latest_cleared.append(platform)

    async def create_release(self, release):
        release.id = uuid4()
        self.release = release
        return release


class FakeTokenRepository:
    def __init__(self, session, token=None):
        self.session = session
        self.token = token
        self.looked_up_hashes = []

    async def get_by_hash_for_update(self, token_hash):
        self.looked_up_hashes.append(token_hash)
        if self.token and self.token.token_hash == token_hash:
            return self.token
        return next(
            (
                item
                for item in self.session.added
                if isinstance(item, DownloadToken) and item.token_hash == token_hash
            ),
            None,
        )

    async def get_with_release_for_update(self, token_hash):
        self.looked_up_hashes.append(token_hash)
        if self.token and self.token.token_hash == token_hash:
            return self.token
        return None

    async def get_with_release(self, token_hash):
        self.looked_up_hashes.append(token_hash)
        if self.token and self.token.token_hash == token_hash:
            return self.token
        return None

    async def get_by_id_for_update(self, token_id):
        if self.token and self.token.id == token_id:
            return self.token
        return next(
            (
                item
                for item in self.session.added
                if isinstance(item, DownloadToken) and item.id == token_id
            ),
            None,
        )


class FakeStorage:
    def __init__(self):
        self.verified = []
        self.downloaded = []

    async def verify_asset(self, asset_id):
        self.verified.append(asset_id)
        return "farmtrack-1.2.3.apk", 1024

    async def create_download_response(self, asset_id, *, file_name):
        self.downloaded.append((asset_id, file_name))
        return RedirectResponse("https://github.com/downloads/farmtrack.apk")


class FakeEmail:
    def __init__(self, *, failure=None, is_configured=True):
        self.sent = []
        self.failure = failure
        self.is_configured = is_configured

    async def send_release_download_invitation(self, **kwargs):
        if self.failure:
            raise self.failure
        self.sent.append(kwargs)


class FakeRecipientRepository:
    def __init__(self, users=None, farms_by_user=None):
        self.users = users or {}
        self.farms_by_user = farms_by_user or {}

    async def get_recipients(self, user_ids):
        return (
            {user_id: self.users[user_id] for user_id in user_ids if user_id in self.users},
            {user_id: self.farms_by_user.get(user_id, []) for user_id in user_ids},
        )

    async def list_recipients(self, *, search, limit, offset):
        users = list(self.users.values())[offset : offset + limit]
        return users, len(self.users), self.farms_by_user


def create_release(**overrides):
    values = {
        "version": "1.2.3",
        "version_code": 123,
        "platform": "android",
        "github_asset_id": 123456,
        "file_name": "farmtrack-1.2.3.apk",
        "file_size": 1024,
        "release_notes": "Bug fixes",
        "is_active": True,
        "is_latest": True,
    }
    values.update(overrides)
    return SimpleNamespace(id=uuid4(), **values)


def make_service(
    monkeypatch,
    *,
    session=None,
    release_repository=None,
    token_repository=None,
    storage=None,
    email=None,
    recipient_repository=None,
):
    session = session or FakeSession()
    release_repository = release_repository or FakeReleaseRepository()
    storage = storage or FakeStorage()
    email = email or FakeEmail()
    token_repository = token_repository or FakeTokenRepository(session)
    recipient_repository = recipient_repository or FakeRecipientRepository()
    monkeypatch.setattr(
        "app.services.app_release_service.AppReleaseRepository",
        lambda _session: release_repository,
    )
    monkeypatch.setattr(
        "app.services.app_release_service.DownloadTokenRepository",
        lambda _session: token_repository,
    )
    monkeypatch.setattr(
        "app.services.app_release_service.AppReleaseRecipientRepository",
        lambda _session: recipient_repository,
    )
    return (
        AppReleaseService(session, storage_service=storage, email_service=email),
        session,
        release_repository,
        token_repository,
        storage,
        email,
    )


@pytest.mark.asyncio
async def test_register_release_verifies_asset_and_uses_github_metadata(monkeypatch):
    service, _session, repository, _tokens, storage, _email = make_service(
        monkeypatch
    )
    request = AppReleaseCreate(
        version="1.2.3",
        version_code=123,
        github_asset_id=123456,
        is_latest=True,
    )

    release = await service.register_release(request)

    assert storage.verified == [123456]
    assert repository.latest_cleared == ["android"]
    assert release.github_asset_id == 123456
    assert release.file_name == "farmtrack-1.2.3.apk"
    assert release.file_size == 1024


@pytest.mark.asyncio
async def test_register_release_rejects_duplicate_version_code(monkeypatch):
    service, session, _repo, _tokens, storage, _email = make_service(
        monkeypatch,
        release_repository=FakeReleaseRepository(
            release=create_release(),
            duplicate=True,
        ),
    )
    request = AppReleaseCreate(
        version="1.2.3",
        version_code=123,
        github_asset_id=123456,
    )

    with pytest.raises(ConflictError):
        await service.register_release(request)

    assert storage.verified == [123456]
    assert session.commits == 0


@pytest.mark.parametrize(
    "values",
    [
        {"version": "not-a-version"},
        {"version_code": 0},
        {"github_asset_id": 0},
        {"platform": "ios"},
    ],
)
def test_release_schema_rejects_invalid_metadata(values):
    request = {
        "version": "1.2.3",
        "version_code": 123,
        "github_asset_id": 123456,
    }
    request.update(values)
    with pytest.raises(ValidationError):
        AppReleaseCreate(**request)


def test_github_release_settings_require_repository_and_token_together():
    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql+asyncpg://localhost/farmtrack",
            jwt_secret_key="x" * 32,
            github_release_repository="owner/backend",
            _env_file=None,
        )

    configured = Settings(
        database_url="postgresql+asyncpg://localhost/farmtrack",
        jwt_secret_key="x" * 32,
        github_release_repository="owner/backend",
        github_release_token="server-only-token",
        _env_file=None,
    )
    assert configured.github_release_repository == "owner/backend"
    assert configured.github_release_token.get_secret_value() == "server-only-token"


@pytest.mark.asyncio
async def test_download_invitation_persists_only_hashed_token(monkeypatch):
    release = create_release()
    monkeypatch.setattr(
        settings,
        "app_public_base_url",
        "https://api.farmtrack.example",
    )
    service, session, _repo, _tokens, _storage, email = make_service(
        monkeypatch,
        release_repository=FakeReleaseRepository(release=release),
    )

    token = await service.send_download_invitation(
        release_id=release.id,
        recipient_email="  person@example.com ",
    )
    raw_token = email.sent[0]["download_url"].rsplit("/", 1)[-1]

    assert token.delivery_status == "sent"
    assert token.recipient_email == "person@example.com"
    assert token.token_hash == hashlib.sha256(raw_token.encode()).hexdigest()
    assert raw_token not in token.token_hash
    assert session.commits == 2


@pytest.mark.asyncio
async def test_release_recipient_directory_includes_linked_farm_contacts(monkeypatch):
    user_id = uuid4()
    farm_id = uuid4()
    user = SimpleNamespace(id=user_id, email="person@example.com")
    farm = SimpleNamespace(
        id=farm_id,
        name="Green Farm",
        phone_number="+254712345678",
        email="farm@example.com",
    )
    service, *_ = make_service(
        monkeypatch,
        recipient_repository=FakeRecipientRepository(
            users={user_id: user},
            farms_by_user={user_id: [farm]},
        ),
    )

    page = await service.list_release_recipients(
        search="green",
        limit=25,
        offset=0,
    )

    assert page.total == 1
    assert page.items[0].email == user.email
    assert page.items[0].farms[0].farm_id == farm_id
    assert page.items[0].farms[0].phone_number == farm.phone_number
    assert page.items[0].farms[0].email == farm.email


@pytest.mark.asyncio
async def test_failed_download_email_revokes_pending_token(monkeypatch):
    release = create_release()
    monkeypatch.setattr(
        settings,
        "app_public_base_url",
        "https://api.farmtrack.example",
    )
    service, session, _repo, _tokens, _storage, _email = make_service(
        monkeypatch,
        release_repository=FakeReleaseRepository(release=release),
        email=FakeEmail(failure=RuntimeError("provider unavailable")),
    )

    with pytest.raises(AppError) as error:
        await service.send_download_invitation(
            release_id=release.id,
            recipient_email="person@example.com",
        )

    assert error.value.status_code == 502
    assert session.added[0].delivery_status == "failed"
    assert session.added[0].revoked_at is not None
    assert session.commits == 2


@pytest.mark.asyncio
async def test_whatsapp_invitation_returns_link_and_persists_prepared_token(monkeypatch):
    release = create_release()
    user_id = uuid4()
    farm_id = uuid4()
    user = SimpleNamespace(id=user_id, email="person@example.com")
    farm = SimpleNamespace(
        id=farm_id,
        name="Green Farm",
        phone_number="+254 712 345 678",
        email=None,
    )
    monkeypatch.setattr(
        settings,
        "app_public_base_url",
        "https://api.farmtrack.example/",
    )
    email = FakeEmail(is_configured=False)
    service, session, _repo, _tokens, _storage, _email = make_service(
        monkeypatch,
        release_repository=FakeReleaseRepository(release=release),
        email=email,
        recipient_repository=FakeRecipientRepository(
            users={user_id: user},
            farms_by_user={user_id: [farm]},
        ),
    )

    results = await service.send_bulk_download_invitations(
        release_id=release.id,
        request=BulkDownloadInvitationRequest(
            channel="whatsapp",
            recipients=[
                BulkInvitationRecipient(user_id=user_id, farm_id=farm_id),
            ],
        ),
    )

    token = session.added[0]
    wa_url = urlsplit(results[0].whatsapp_url)
    message = parse_qs(wa_url.query)["text"][0]
    share_url = message.split()[-1]
    raw_token = share_url.split("/api/v1/downloads/", 1)[1].split("/", 1)[0]
    assert results[0].email_status == "not_requested"
    assert wa_url.netloc == "wa.me"
    assert wa_url.path == "/254712345678"
    assert "Hi! 👋" in message
    assert "Version 1.2.3" in message
    assert "What’s new:\nBug fixes" in message
    assert share_url.endswith(f"/{raw_token}/share")
    assert token.delivery_channel == "whatsapp"
    assert token.delivery_status == "prepared"
    assert token.token_hash == hashlib.sha256(raw_token.encode()).hexdigest()
    assert email.sent == []


@pytest.mark.asyncio
async def test_custom_whatsapp_number_prepares_link_without_email(monkeypatch):
    release = create_release()
    monkeypatch.setattr(
        settings,
        "app_public_base_url",
        "https://api.farmtrack.example/",
    )
    service, session, _repo, _tokens, _storage, email = make_service(
        monkeypatch,
        release_repository=FakeReleaseRepository(release=release),
    )

    invitation = await service.prepare_whatsapp_download_invitation(
        release_id=release.id,
        request=WhatsAppInvitationRequest(phone_number="+254 712 345 678"),
    )

    token = session.added[0]
    wa_url = urlsplit(invitation.whatsapp_url)
    message = parse_qs(wa_url.query)["text"][0]
    share_url = message.split()[-1]
    raw_token = share_url.split("/api/v1/downloads/", 1)[1].split("/", 1)[0]
    assert invitation.recipient_phone == "254712345678"
    assert invitation.delivery_status == "prepared"
    assert "FarmTrack" in invitation.share_message
    assert f"Version {release.version}" in invitation.share_message
    assert "What’s new:" in invitation.share_message
    assert invitation.download_url == (
        f"https://api.farmtrack.example/api/v1/downloads/{raw_token}"
    )
    assert invitation.share_url == share_url
    assert invitation.share_url.endswith(f"/{raw_token}/share")
    assert invitation.download_url in invitation.share_url
    assert wa_url.netloc == "wa.me"
    assert wa_url.path == "/254712345678"
    assert token.recipient_email is None
    assert token.recipient_phone == "254712345678"
    assert token.delivery_channel == "whatsapp"
    assert token.delivery_status == "prepared"
    assert token.token_hash == hashlib.sha256(raw_token.encode()).hexdigest()
    assert email.sent == []
    assert session.commits == 1


@pytest.mark.asyncio
async def test_release_share_invitation_does_not_require_a_phone_number(monkeypatch):
    release = create_release()
    monkeypatch.setattr(
        settings,
        "app_public_base_url",
        "https://api.farmtrack.example/",
    )
    service, session, _repo, _tokens, _storage, email = make_service(
        monkeypatch,
        release_repository=FakeReleaseRepository(release=release),
    )

    invitation = await service.prepare_release_share_invitation(
        release_id=release.id,
    )

    token = session.added[0]
    wa_url = urlsplit(invitation.whatsapp_url)
    message = parse_qs(wa_url.query)["text"][0]
    raw_token = invitation.download_url.rsplit("/", 1)[-1]
    assert wa_url.netloc == "wa.me"
    assert wa_url.path == "/"
    assert invitation.share_url == f"{invitation.download_url}/share"
    assert invitation.share_url in message
    assert invitation.preview_image_url.endswith(
        "/api/v1/app-releases/share-preview.png"
    )
    assert token.recipient_email is None
    assert token.recipient_phone is None
    assert token.delivery_status == "prepared"
    assert token.token_hash == hashlib.sha256(raw_token.encode()).hexdigest()
    assert email.sent == []


@pytest.mark.asyncio
async def test_download_share_page_has_social_preview_image_and_private_cta(monkeypatch):
    raw_token = "a" * 32
    release = create_release()
    token = DownloadToken(
        id=uuid4(),
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        release_id=release.id,
        recipient_email=None,
        recipient_phone=None,
        delivery_channel="whatsapp",
        delivery_status="prepared",
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        release=release,
    )
    monkeypatch.setattr(
        settings,
        "app_public_base_url",
        "https://api.farmtrack.example",
    )
    service, _session, _repo, _tokens, _storage, _email = make_service(
        monkeypatch,
        token_repository=FakeTokenRepository(FakeSession(), token=token),
    )

    page = await service.create_download_share_page(raw_token)

    assert page.media_type == "text/html"
    assert 'property="og:image"' in page.body.decode()
    assert (
        "https://api.farmtrack.example/api/v1/app-releases/share-preview.png"
        in page.body.decode()
    )
    assert (
        f"https://api.farmtrack.example/api/v1/downloads/{raw_token}"
        in page.body.decode()
    )
    assert "Download FarmTrack for Android" in page.body.decode()


@pytest.mark.asyncio
async def test_custom_whatsapp_number_requires_country_code(monkeypatch):
    release = create_release()
    monkeypatch.setattr(
        settings,
        "app_public_base_url",
        "https://api.farmtrack.example",
    )
    service, session, *_ = make_service(
        monkeypatch,
        release_repository=FakeReleaseRepository(release=release),
    )

    with pytest.raises(AppError) as error:
        await service.prepare_whatsapp_download_invitation(
            release_id=release.id,
            request=WhatsAppInvitationRequest(phone_number="0712345678"),
        )

    assert error.value.code == "INVALID_WHATSAPP_PHONE"
    assert session.added == []


@pytest.mark.asyncio
async def test_both_channels_keep_whatsapp_invitation_when_email_is_unconfigured(
    monkeypatch,
):
    release = create_release()
    user_id = uuid4()
    farm_id = uuid4()
    user = SimpleNamespace(id=user_id, email="person@example.com")
    farm = SimpleNamespace(
        id=farm_id,
        name="Green Farm",
        phone_number="254712345678",
        email=None,
    )
    monkeypatch.setattr(
        settings,
        "app_public_base_url",
        "https://api.farmtrack.example",
    )
    service, session, _repo, _tokens, _storage, email = make_service(
        monkeypatch,
        release_repository=FakeReleaseRepository(release=release),
        email=FakeEmail(is_configured=False),
        recipient_repository=FakeRecipientRepository(
            users={user_id: user},
            farms_by_user={user_id: [farm]},
        ),
    )

    results = await service.send_bulk_download_invitations(
        release_id=release.id,
        request=BulkDownloadInvitationRequest(
            channel="both",
            recipients=[
                BulkInvitationRecipient(user_id=user_id, farm_id=farm_id),
            ],
        ),
    )

    assert results[0].email_status == "failed"
    assert results[0].whatsapp_url is not None
    assert session.added[0].delivery_status == "prepared"
    assert session.added[0].delivery_channel == "both"
    assert email.sent == []


@pytest.mark.asyncio
async def test_both_channels_send_email_and_prepare_whatsapp_link(monkeypatch):
    release = create_release()
    user_id = uuid4()
    farm_id = uuid4()
    user = SimpleNamespace(id=user_id, email="person@example.com")
    farm = SimpleNamespace(
        id=farm_id,
        name="Green Farm",
        phone_number="+254712345678",
        email=None,
    )
    monkeypatch.setattr(
        settings,
        "app_public_base_url",
        "https://api.farmtrack.example",
    )
    email = FakeEmail()
    service, session, _repo, _tokens, _storage, _email = make_service(
        monkeypatch,
        release_repository=FakeReleaseRepository(release=release),
        email=email,
        recipient_repository=FakeRecipientRepository(
            users={user_id: user},
            farms_by_user={user_id: [farm]},
        ),
    )

    results = await service.send_bulk_download_invitations(
        release_id=release.id,
        request=BulkDownloadInvitationRequest(
            channel="both",
            recipients=[
                BulkInvitationRecipient(user_id=user_id, farm_id=farm_id),
            ],
        ),
    )

    assert results[0].email_status == "sent"
    assert results[0].whatsapp_url is not None
    assert session.added[0].delivery_status == "sent"
    assert session.added[0].delivery_channel == "both"
    assert len(email.sent) == 1
    assert email.sent[0]["recipient_email"] == user.email


@pytest.mark.asyncio
async def test_failed_email_keeps_whatsapp_invitation_usable(monkeypatch):
    release = create_release()
    user_id = uuid4()
    farm_id = uuid4()
    user = SimpleNamespace(id=user_id, email="person@example.com")
    farm = SimpleNamespace(
        id=farm_id,
        name="Green Farm",
        phone_number="+254712345678",
        email=None,
    )
    monkeypatch.setattr(
        settings,
        "app_public_base_url",
        "https://api.farmtrack.example",
    )
    service, session, _repo, _tokens, _storage, _email = make_service(
        monkeypatch,
        release_repository=FakeReleaseRepository(release=release),
        email=FakeEmail(failure=RuntimeError("provider unavailable")),
        recipient_repository=FakeRecipientRepository(
            users={user_id: user},
            farms_by_user={user_id: [farm]},
        ),
    )

    results = await service.send_bulk_download_invitations(
        release_id=release.id,
        request=BulkDownloadInvitationRequest(
            channel="both",
            recipients=[
                BulkInvitationRecipient(user_id=user_id, farm_id=farm_id),
            ],
        ),
    )

    assert results[0].email_status == "failed"
    assert results[0].whatsapp_url is not None
    assert session.added[0].delivery_status == "prepared"
    assert session.added[0].revoked_at is None


@pytest.mark.asyncio
async def test_whatsapp_invitation_requires_international_farm_phone(monkeypatch):
    release = create_release()
    user_id = uuid4()
    farm_id = uuid4()
    user = SimpleNamespace(id=user_id, email="person@example.com")
    farm = SimpleNamespace(
        id=farm_id,
        name="Green Farm",
        phone_number="0712345678",
        email=None,
    )
    service, session, _repo, _tokens, _storage, _email = make_service(
        monkeypatch,
        release_repository=FakeReleaseRepository(release=release),
        recipient_repository=FakeRecipientRepository(
            users={user_id: user},
            farms_by_user={user_id: [farm]},
        ),
    )
    monkeypatch.setattr(
        settings,
        "app_public_base_url",
        "https://api.farmtrack.example",
    )

    with pytest.raises(AppError) as error:
        await service.send_bulk_download_invitations(
            release_id=release.id,
            request=BulkDownloadInvitationRequest(
                channel="whatsapp",
                recipients=[
                    BulkInvitationRecipient(user_id=user_id, farm_id=farm_id),
                ],
            ),
        )

    assert error.value.code == "INVALID_WHATSAPP_PHONE"
    assert session.added == []


@pytest.mark.asyncio
@pytest.mark.parametrize("delivery_status", ["sent", "prepared"])
async def test_valid_download_uses_github_asset_and_tracks_access(
    monkeypatch,
    delivery_status,
):
    release = create_release()
    token = SimpleNamespace(
        id=uuid4(),
        token_hash=hashlib.sha256(b"raw-download-token").hexdigest(),
        release_id=release.id,
        recipient_email="person@example.com",
        delivery_status=delivery_status,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        revoked_at=None,
        access_count=0,
        last_accessed_at=None,
        release=release,
    )
    session = FakeSession()
    tokens = FakeTokenRepository(session, token=token)
    service, _session, _repo, _tokens, storage, _email = make_service(
        monkeypatch,
        session=session,
        token_repository=tokens,
    )

    response = await service.create_download_response("raw-download-token")

    assert response.status_code == 307
    assert storage.downloaded == [
        (release.github_asset_id, release.file_name)
    ]
    assert token.access_count == 1
    assert token.last_accessed_at is not None
    assert tokens.looked_up_hashes == [
        hashlib.sha256(b"raw-download-token").hexdigest()
    ]


@pytest.mark.asyncio
async def test_expired_or_invalid_token_does_not_download(monkeypatch):
    release = create_release()
    token = SimpleNamespace(
        id=uuid4(),
        token_hash=hashlib.sha256(b"expired-token").hexdigest(),
        release_id=release.id,
        recipient_email="person@example.com",
        delivery_status="sent",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        revoked_at=None,
        access_count=0,
        last_accessed_at=None,
        release=release,
    )
    storage = FakeStorage()
    service, _session, _repo, _tokens, _storage, _email = make_service(
        monkeypatch,
        token_repository=FakeTokenRepository(FakeSession(), token=token),
        storage=storage,
    )

    with pytest.raises(AppError) as error:
        await service.create_download_response("expired-token")
    assert error.value.status_code == 410
    assert storage.downloaded == []

    with pytest.raises(ResourceNotFoundError):
        await service.create_download_response("unknown-token")
    assert storage.downloaded == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("delivery_status", "revoked", "is_active", "expected_status"),
    [
        ("pending", None, True, 404),
        ("sent", datetime.now(timezone.utc), True, 410),
        ("sent", None, False, 410),
    ],
)
async def test_pending_revoked_and_inactive_downloads_are_rejected(
    monkeypatch,
    delivery_status,
    revoked,
    is_active,
    expected_status,
):
    release = create_release(is_active=is_active)
    token = SimpleNamespace(
        id=uuid4(),
        token_hash=hashlib.sha256(b"blocked-token").hexdigest(),
        release_id=release.id,
        recipient_email="person@example.com",
        delivery_status=delivery_status,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        revoked_at=revoked,
        access_count=0,
        last_accessed_at=None,
        release=release,
    )
    storage = FakeStorage()
    service, _session, _repo, _tokens, _storage, _email = make_service(
        monkeypatch,
        token_repository=FakeTokenRepository(FakeSession(), token=token),
        storage=storage,
    )

    with pytest.raises(AppError) as error:
        await service.create_download_response("blocked-token")

    assert error.value.status_code == expected_status
    assert storage.downloaded == []


@pytest.mark.asyncio
async def test_download_invitation_can_be_revoked(monkeypatch):
    token = SimpleNamespace(id=uuid4(), revoked_at=None)
    session = FakeSession()
    token_repository = FakeTokenRepository(session, token=token)
    service, _session, _repo, _tokens, _storage, _email = make_service(
        monkeypatch,
        session=session,
        token_repository=token_repository,
    )

    await service.revoke_download_invitation(token.id)

    assert token.revoked_at is not None
    assert session.commits == 1


def test_download_token_path_is_redacted_from_request_logs():
    from app.core.logging import redact_sensitive_path

    assert redact_sensitive_path("/api/v1/downloads/secret-token") == (
        "/api/v1/downloads/[REDACTED]"
    )


@pytest.mark.asyncio
async def test_release_admin_uses_backend_email_allowlist(monkeypatch):
    admin = SimpleNamespace(email="ADMIN@example.com")
    monkeypatch.setattr(
        settings,
        "app_release_admin_emails",
        ["admin@example.com"],
    )
    assert await require_app_release_admin(admin) is admin

    monkeypatch.setattr(settings, "app_release_admin_emails", [])
    with pytest.raises(AuthorizationError):
        await require_app_release_admin(admin)


@pytest.mark.asyncio
async def test_github_storage_verifies_asset_without_exposing_token(monkeypatch):
    monkeypatch.setattr(settings, "github_release_repository", "owner/backend")
    monkeypatch.setattr(
        settings,
        "github_release_token",
        SecretStr("server-only-token"),
    )
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "id": 123456,
                "name": "farmtrack.apk",
                "size": 1024,
                "state": "uploaded",
            },
        )

    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "app.services.github_release_storage_service.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )

    assert await GitHubReleaseStorageService().verify_asset(123456) == (
        "farmtrack.apk",
        1024,
    )
    request = captured[0]
    assert request.method == "GET"
    assert request.headers["Authorization"] == "Bearer server-only-token"
    assert request.url.path == "/repos/owner/backend/releases/assets/123456"


@pytest.mark.asyncio
async def test_github_storage_redirects_to_temporary_asset_url(monkeypatch):
    monkeypatch.setattr(settings, "github_release_repository", "owner/backend")
    monkeypatch.setattr(
        settings,
        "github_release_token",
        SecretStr("server-only-token"),
    )
    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            302,
            headers={
                "Location": (
                    "https://release-assets.githubusercontent.com/file.apk"
                    "?token=short"
                )
            },
        )
    )
    monkeypatch.setattr(
        "app.services.github_release_storage_service.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )

    response = await GitHubReleaseStorageService().create_download_response(
        123456,
        file_name="farmtrack.apk",
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith(
        "https://release-assets.githubusercontent.com/"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata",
    [
        {"id": 123456, "name": "farmtrack.zip", "size": 1024, "state": "uploaded"},
        {"id": 123456, "name": "farmtrack.apk", "size": 0, "state": "uploaded"},
        {"id": 123456, "name": "farmtrack.apk", "size": 1024, "state": "open"},
        {"id": 654321, "name": "farmtrack.apk", "size": 1024, "state": "uploaded"},
    ],
)
async def test_github_storage_rejects_invalid_asset_metadata(monkeypatch, metadata):
    monkeypatch.setattr(settings, "github_release_repository", "owner/backend")
    monkeypatch.setattr(
        settings,
        "github_release_token",
        SecretStr("server-only-token"),
    )
    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, json=metadata)
    )
    monkeypatch.setattr(
        "app.services.github_release_storage_service.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )

    with pytest.raises(AppError) as error:
        await GitHubReleaseStorageService().verify_asset(123456)
    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_github_storage_streams_asset_when_api_returns_content(monkeypatch):
    monkeypatch.setattr(settings, "github_release_repository", "owner/backend")
    monkeypatch.setattr(
        settings,
        "github_release_token",
        SecretStr("server-only-token"),
    )
    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            content=b"apk-content",
            headers={"Content-Type": "application/octet-stream"},
        )
    )
    monkeypatch.setattr(
        "app.services.github_release_storage_service.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )

    response = await GitHubReleaseStorageService().create_download_response(
        123456,
        file_name="farmtrack.apk",
    )
    assert response.status_code == 200
    assert response.headers["content-disposition"].endswith(
        "filename*=UTF-8''farmtrack.apk"
    )
    chunks = [chunk async for chunk in response.body_iterator]
    assert b"".join(chunks) == b"apk-content"
    await response.background()


@pytest.mark.asyncio
async def test_github_storage_rejects_untrusted_download_host(monkeypatch):
    monkeypatch.setattr(settings, "github_release_repository", "owner/backend")
    monkeypatch.setattr(
        settings,
        "github_release_token",
        SecretStr("server-only-token"),
    )
    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            302,
            headers={"Location": "https://attacker.example/file.apk"},
        )
    )
    monkeypatch.setattr(
        "app.services.github_release_storage_service.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )

    with pytest.raises(AppError) as error:
        await GitHubReleaseStorageService().create_download_response(
            123456,
            file_name="farmtrack.apk",
        )
    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_download_endpoint_returns_storage_response(monkeypatch):
    from app.api.v1.endpoints import app_releases

    class DownloadService:
        def __init__(self, _session):
            pass

        async def create_download_response(self, token):
            assert token == "opaque-download-token"
            return RedirectResponse("https://github.com/downloads/farmtrack.apk")

    monkeypatch.setattr(app_releases, "AppReleaseService", DownloadService)
    response = await app_releases.download_app(
        token="opaque-download-token",
        session=FakeSession(),
    )

    assert response.status_code == 307
    assert response.headers["location"] == "https://github.com/downloads/farmtrack.apk"
