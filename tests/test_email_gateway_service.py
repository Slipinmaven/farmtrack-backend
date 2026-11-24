import json
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings, settings
from app.services.email_gateway_service import FarmTrackEmailService

GATEWAY_URL = "https://script.google.com/macros/s/test/exec"
GATEWAY_SECRET = "test-gateway-secret"


@pytest.fixture(autouse=True)
def configured_gateway(monkeypatch):
    monkeypatch.setattr(settings, "email_gateway_url", GATEWAY_URL)
    monkeypatch.setattr(settings, "email_gateway_secret", SecretStr(GATEWAY_SECRET))
    monkeypatch.setattr(settings, "email_gateway_timeout_seconds", 15.0)
    monkeypatch.setattr(settings, "farmtrack_app_url", "farmtrack://farm-team")


async def send_with_response(handler, callback, *, expected_request_count=1):
    requests = []

    async def record_request(request):
        requests.append(request)
        return await handler(request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(record_request),
        timeout=1,
        follow_redirects=True,
    ) as client:
        await callback(FarmTrackEmailService(client))

    assert len(requests) == expected_request_count
    return requests[0]


@pytest.mark.asyncio
async def test_invitation_sends_text_and_styled_html_through_gateway():
    membership = SimpleNamespace(
        farm=SimpleNamespace(name="Green Valley"),
        role="worker",
        user=SimpleNamespace(email="worker@example.com"),
    )
    delivery_id = uuid4()

    async def deliver(service):
        await service.send_farm_invitation(
            membership=membership,
            idempotency_key=delivery_id,
        )

    async def gateway(_request):
        return httpx.Response(200, json={"ok": True})

    request = await send_with_response(gateway, deliver)
    assert request.url == GATEWAY_URL
    assert request.method == "POST"
    payload = json.loads(request.content)
    assert payload["apiKey"] == GATEWAY_SECRET
    assert payload["to"] == "worker@example.com"
    assert payload["subject"] == "Invitation to join Green Valley on FarmTrack"
    assert "farmtrack://farm-team" in payload["textBody"]
    assert "You're invited!" in payload["htmlBody"]
    assert "Green Valley" in payload["htmlBody"]
    assert 'href="farmtrack://farm-team"' in payload["htmlBody"]
    assert "Accept using the FarmTrack account registered to the email address" in payload["htmlBody"]
    assert "More &gt; Team &amp; invitations" in payload["htmlBody"]
    assert "FarmTrack will never include" in payload["textBody"]
    assert "long-initial-password" not in payload["textBody"]


@pytest.mark.asyncio
async def test_invitation_html_escapes_farm_name_and_app_link(monkeypatch):
    monkeypatch.setattr(
        settings,
        "farmtrack_app_url",
        'farmtrack://farm-team?name="x"&open=1',
    )
    membership = SimpleNamespace(
        farm=SimpleNamespace(name='<Farm "X">'),
        role="worker",
        user=SimpleNamespace(email="worker@example.com"),
    )

    async def deliver(service):
        await service.send_farm_invitation(
            membership=membership,
            idempotency_key=uuid4(),
        )

    async def gateway(_request):
        return httpx.Response(200, json={"ok": True})

    request = await send_with_response(gateway, deliver)
    html_body = json.loads(request.content)["htmlBody"]
    assert "&lt;Farm &quot;X&quot;&gt;" in html_body
    assert 'href="farmtrack://farm-team?name=&quot;x&quot;&amp;open=1"' in html_body
    assert '<Farm "X">' not in html_body


@pytest.mark.asyncio
async def test_release_email_preserves_plain_text_and_html_content():
    async def deliver(service):
        await service.send_release_download_invitation(
            recipient_email="recipient@example.com",
            version="1.2.3",
            release_notes="<New fixes & improvements>",
            download_url="https://api.example.com/api/v1/downloads/secret-token",
            download_password="ABCD2345EFGH6789",
            expires_at=datetime(2026, 11, 16, tzinfo=timezone.utc),
            delivery_id=uuid4(),
        )

    async def gateway(_request):
        return httpx.Response(200, json={"ok": True})

    request = await send_with_response(gateway, deliver)
    payload = json.loads(request.content)
    assert payload["subject"] == "Download FarmTrack for Android"
    assert "secret-token" in payload["textBody"]
    assert "Download password: ABCD2345EFGH6789" in payload["textBody"]
    assert "ABCD2345EFGH6789" in payload["htmlBody"]
    assert "install apps from this source" in payload["textBody"]
    assert "&lt;New fixes &amp; improvements&gt;" in payload["htmlBody"]
    assert "November 16, 2026" in payload["htmlBody"]


@pytest.mark.asyncio
async def test_test_email_uses_plain_text_and_gateway_secret():
    async def deliver(service):
        await service.send_test_email("recipient@example.com")

    async def gateway(_request):
        return httpx.Response(200, json={"ok": True})

    request = await send_with_response(gateway, deliver)
    payload = json.loads(request.content)
    assert payload["to"] == "recipient@example.com"
    assert payload["subject"] == "FarmTrack email configuration test"
    assert "Email Gateway is working" in payload["textBody"]
    assert "htmlBody" not in payload


@pytest.mark.asyncio
async def test_account_deletion_notice_explains_scheduled_date_and_account_security():
    async def deliver(service):
        await service.send_account_deletion_notice(
            recipient_email="owner@example.com",
            scheduled_for=datetime(2026, 12, 12, tzinfo=timezone.utc),
        )

    async def gateway(_request):
        return httpx.Response(200, json={"ok": True})

    request = await send_with_response(gateway, deliver)
    payload = json.loads(request.content)
    assert payload["to"] == "owner@example.com"
    assert payload["subject"] == "Your FarmTrack account deletion is scheduled"
    assert "December 12, 2026 (UTC)" in payload["textBody"]
    assert "Restore scheduled account deletion" in payload["textBody"]
    assert "sign in again" in payload["textBody"].lower()
    assert "change your password" in payload["textBody"].lower()
    assert "December 12, 2026" in payload["htmlBody"]
    assert "Permanent deletion date" in payload["htmlBody"]
    assert "If you did not request this" in payload["htmlBody"]
    assert "owned farms will be paused" in payload["textBody"]
    assert "confirm" not in payload["textBody"].lower()


@pytest.mark.asyncio
async def test_account_restored_notice_confirms_recovery_and_gives_security_steps():
    async def deliver(service):
        await service.send_account_restored_notice(
            recipient_email="owner@example.com",
        )

    async def gateway(_request):
        return httpx.Response(200, json={"ok": True})

    request = await send_with_response(gateway, deliver)
    payload = json.loads(request.content)

    assert payload["to"] == "owner@example.com"
    assert payload["subject"] == "Your FarmTrack account is restored"
    assert "deletion request has been cancelled" in payload["textBody"]
    assert "account access is active again" in payload["textBody"]
    assert "farms and team memberships" in payload["textBody"]
    assert "Password & sign-in activity" in payload["textBody"]
    assert "account is restored" in payload["htmlBody"]
    assert "Your workspace is available again" in payload["htmlBody"]
    assert "If you didn’t cancel this request" not in payload["htmlBody"]
    assert "Wasn’t this you?" in payload["htmlBody"]
    assert 'name="viewport"' in payload["htmlBody"]
    assert "max-width:560px" in payload["htmlBody"]
    assert "background-color:#EAF5EE" in payload["htmlBody"]
    assert "http://" not in payload["htmlBody"]
    assert "https://" not in payload["htmlBody"]


@pytest.mark.asyncio
async def test_farm_deletion_notice_explains_recovery_and_scheduled_date():
    async def deliver(service):
        await service.send_farm_deletion_notice(
            recipient_email="owner@example.com",
            farm_name="North Field",
            scheduled_for=datetime(2026, 12, 12, tzinfo=timezone.utc),
        )

    async def gateway(_request):
        return httpx.Response(200, json={"ok": True})

    request = await send_with_response(gateway, deliver)
    payload = json.loads(request.content)
    assert payload["to"] == "owner@example.com"
    assert payload["subject"] == "A FarmTrack farm deletion is scheduled"
    assert "North Field" in payload["textBody"]
    assert "December 12, 2026 (UTC)" in payload["textBody"]
    assert "30-day recovery period" in payload["textBody"]
    assert "Account &amp; access" in payload["htmlBody"]
    assert "If you did not request this" in payload["htmlBody"]
    assert "Permanent deletion date" in payload["htmlBody"]


@pytest.mark.asyncio
async def test_farm_member_left_notice_is_clear_and_escapes_html():
    async def deliver(service):
        await service.send_farm_member_left_notice(
            recipient_email="owner@example.com",
            farm_name="North <Field>",
            member_email="member@example.com",
        )

    async def gateway(_request):
        return httpx.Response(200, json={"ok": True})

    request = await send_with_response(gateway, deliver)
    payload = json.loads(request.content)

    assert payload["to"] == "owner@example.com"
    assert payload["subject"] == "A member left North <Field>"
    assert "member@example.com has left North <Field>" in payload["textBody"]
    assert "farm and its records have not been deleted" in payload["textBody"]
    assert "North &lt;Field&gt;" in payload["htmlBody"]
    assert "member@example.com" in payload["htmlBody"]
    assert 'name="viewport"' in payload["htmlBody"]


@pytest.mark.asyncio
async def test_farm_leave_confirmation_says_owner_was_notified():
    async def deliver(service):
        await service.send_farm_left_confirmation(
            recipient_email="member@example.com",
            farm_name="North Field",
            owner_notified=True,
        )

    async def gateway(_request):
        return httpx.Response(200, json={"ok": True})

    request = await send_with_response(gateway, deliver)
    payload = json.loads(request.content)

    assert payload["to"] == "member@example.com"
    assert payload["subject"] == "You have left North Field"
    assert "The farm owner has been notified" in payload["textBody"]
    assert "nothing was deleted" in payload["textBody"]
    assert "The farm owner has been notified" in payload["htmlBody"]
    assert 'name="viewport"' in payload["htmlBody"]


@pytest.mark.asyncio
async def test_gateway_rejection_does_not_expose_gateway_error_or_secret():
    async def deliver(service):
        await service.send_test_email("recipient@example.com")

    async def gateway(_request):
        return httpx.Response(
            200,
            json={"ok": False, "error": f"private response {GATEWAY_SECRET}"},
        )

    with pytest.raises(RuntimeError, match="gateway rejected") as error:
        await send_with_response(gateway, deliver)
    assert GATEWAY_SECRET not in str(error.value)
    assert "private response" not in str(error.value)


@pytest.mark.asyncio
async def test_http_error_is_checked_and_provider_body_is_not_exposed():
    async def deliver(service):
        await service.send_test_email("recipient@example.com")

    async def gateway(_request):
        return httpx.Response(502, text=f"private body {GATEWAY_SECRET}")

    with pytest.raises(RuntimeError, match="unsuccessful HTTP status") as error:
        await send_with_response(gateway, deliver)
    assert "502" in str(error.value)
    assert GATEWAY_SECRET not in str(error.value)
    assert "private body" not in str(error.value)


@pytest.mark.asyncio
async def test_google_script_redirect_is_followed_to_gateway_response():
    async def deliver(service):
        await service.send_test_email("recipient@example.com")

    async def gateway(request):
        if request.url.host == "script.google.com":
            return httpx.Response(
                302,
                headers={"Location": "https://script.googleusercontent.com/result"},
            )
        return httpx.Response(200, json={"ok": True})

    request = await send_with_response(
        gateway,
        deliver,
        expected_request_count=2,
    )
    assert request.url.host == "script.google.com"
@pytest.mark.asyncio
async def test_timeout_does_not_expose_request_exception():
    async def deliver(service):
        await service.send_test_email("recipient@example.com")

    async def gateway(_request):
        raise httpx.ReadTimeout(f"timed out {GATEWAY_SECRET}")

    with pytest.raises(RuntimeError, match="timed out") as error:
        await send_with_response(gateway, deliver)
    assert GATEWAY_SECRET not in str(error.value)


@pytest.mark.asyncio
async def test_network_error_does_not_expose_request_exception():
    async def deliver(service):
        await service.send_test_email("recipient@example.com")

    async def gateway(_request):
        raise httpx.ConnectError(f"connection failed {GATEWAY_SECRET}")

    with pytest.raises(RuntimeError, match="request failed") as error:
        await send_with_response(gateway, deliver)
    assert GATEWAY_SECRET not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not json"),
        httpx.Response(200, json=[]),
        httpx.Response(200, json={"ok": "true"}),
    ],
)
async def test_invalid_gateway_responses_are_rejected(response):
    async def deliver(service):
        await service.send_test_email("recipient@example.com")

    async def gateway(_request):
        return response

    with pytest.raises(RuntimeError, match="invalid response"):
        await send_with_response(gateway, deliver)


@pytest.mark.asyncio
async def test_missing_gateway_configuration_fails_clearly(monkeypatch):
    monkeypatch.setattr(settings, "email_gateway_url", None)
    monkeypatch.setattr(settings, "email_gateway_secret", None)
    async with httpx.AsyncClient() as client:
        service = FarmTrackEmailService(client)
        assert service.is_configured is False
        with pytest.raises(RuntimeError, match="not configured"):
            await service.send_test_email("recipient@example.com")


def test_gateway_url_rejects_plain_http_outside_localhost():
    with pytest.raises(ValidationError, match="must use HTTPS"):
        Settings(
            _env_file=None,
            database_url="postgresql+asyncpg://localhost/farmtrack",
            jwt_secret_key="a" * 32,
            email_gateway_url="http://gateway.example.com/email",
            email_gateway_secret="example-secret",
        )


def test_gateway_secret_requires_secret_str_representation():
    config = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://localhost/farmtrack",
        jwt_secret_key="a" * 32,
        email_gateway_url=GATEWAY_URL,
        email_gateway_secret=GATEWAY_SECRET,
    )
    assert config.email_gateway_secret is not None
    assert GATEWAY_SECRET not in str(config.email_gateway_secret)
